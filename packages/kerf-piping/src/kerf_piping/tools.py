"""
kerf_piping LLM tools — P&ID routing + import.

Tools
-----
piping_route_isometric  Route a pipe between equipment nozzles and return fitting counts.
piping_import_pid       Parse a text-format P&ID specification into the data model.
piping_export_svg       Export a P&ID diagram as an SVG string.
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
# piping_min_wall_thickness  (ASME B31.1 §104.1.2 Eq. 7)
# ---------------------------------------------------------------------------

piping_min_wall_thickness_spec = ToolSpec(
    name="piping_min_wall_thickness",
    description=(
        "Calculate the minimum pipe wall thickness per ASME B31.1-2022 §104.1.2 "
        "Equation 7 (Power Piping).  Applies to straight pipe under internal "
        "pressure.  Returns minimum required thickness, ordered minimum thickness "
        "(including mill tolerance), maximum allowable working pressure, and "
        "recommended ASME schedule.  "
        "\n\nFormula (Eq. 7): t = P·D / (2·(S·E + P·y)) + A"
        "\nWhere P = design pressure, D = outside diameter, S = allowable stress, "
        "E = joint efficiency, y = Table 104.1.2-1 coefficient, A = corrosion allowance.  "
        "\n\nDISCLAIMER: ASME B31.1 methods — NOT ASME stamp certified.  "
        "Review by a licensed Professional Engineer required for physical installation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pressure_psi": {
                "type": "number",
                "description": "Internal design gauge pressure (psi).",
            },
            "diameter_in": {
                "type": "number",
                "description": (
                    "Pipe outside diameter (inches).  "
                    "Standard NPS values: 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, "
                    "3.0, 4.0, 6.0 (OD 6.625\"), 8.0 (OD 8.625\"), 10.0, 12.0.  "
                    "Pass the NPS size or the actual OD — both are accepted."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["A106-B", "A53-B", "A312-304", "A312-316"],
                "description": (
                    "Material key for ASME B31.1 Table A-1 allowable stress lookup.  "
                    "A106-B = carbon steel seamless (most common power piping); "
                    "A53-B = ERW/seamless lower grade; "
                    "A312-304 = SS 304; A312-316 = SS 316.  Default 'A106-B'."
                ),
            },
            "temp_F": {
                "type": "number",
                "description": (
                    "Design temperature (°F).  Used to look up allowable stress "
                    "from Table A-1 and y coefficient from Table 104.1.2-1.  "
                    "Default 70 (ambient)."
                ),
            },
            "joint_efficiency": {
                "type": "number",
                "description": (
                    "Longitudinal weld joint efficiency E.  "
                    "1.0 = seamless (default); 0.85 = ERW; 0.80 = furnace-butt-weld."
                ),
            },
            "mill_tolerance_pct": {
                "type": "number",
                "description": (
                    "Under-thickness mill tolerance (%).  "
                    "ASME B36.10M standard = 12.5% (default)."
                ),
            },
            "corrosion_allowance_in": {
                "type": "number",
                "description": (
                    "Corrosion/erosion allowance (inches).  "
                    "Include thread or groove depth if applicable.  "
                    "Default 0.0625\" (1/16\")."
                ),
            },
        },
        "required": ["pressure_psi", "diameter_in"],
    },
)


async def run_piping_min_wall_thickness(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.wall_thickness import (
            min_wall_thickness_b31_1,
            material_allowable_stress,
        )

        pressure_psi = float(args["pressure_psi"])
        diameter_in = float(args["diameter_in"])
        material = str(args.get("material", "A106-B"))
        temp_F = float(args.get("temp_F", 70.0))
        joint_efficiency = float(args.get("joint_efficiency", 1.0))
        mill_tolerance_pct = float(args.get("mill_tolerance_pct", 12.5))
        corrosion_allowance_in = float(args.get("corrosion_allowance_in", 0.0625))

        # Look up allowable stress from Table A-1
        try:
            S = material_allowable_stress(material, temp_F)
        except (KeyError, ValueError) as exc:
            return err_payload(str(exc), "BAD_MATERIAL_OR_TEMP")

        result = min_wall_thickness_b31_1(
            pressure_psi=pressure_psi,
            diameter_in=diameter_in,
            allowable_stress_psi=S,
            joint_efficiency=joint_efficiency,
            mill_tolerance_pct=mill_tolerance_pct,
            corrosion_allowance_in=corrosion_allowance_in,
            temp_F=temp_F,
            material=material,
        )

        payload: dict[str, Any] = {
            "ok": True,
            "material": material,
            "temp_F": temp_F,
            "allowable_stress_psi": round(S, 1),
            **result,
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_WALL_THICKNESS_ERROR")


# ---------------------------------------------------------------------------
# piping_recommend_schedule  (ASME B36.10M schedule selector)
# ---------------------------------------------------------------------------

piping_recommend_schedule_spec = ToolSpec(
    name="piping_recommend_schedule",
    description=(
        "Recommend the thinnest ASME B36.10M pipe schedule whose nominal wall "
        "thickness is ≥ the specified minimum required wall thickness.  "
        "Inputs are the NPS size (in inches) and the minimum wall thickness (inches).  "
        "Returns a schedule code (e.g. '40', '80', '160', 'XXS') or "
        "'EXCEEDS-XXS' if no standard schedule is sufficient.  "
        "\n\nTypical NPS sizes: 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 8.0, 10.0, 12.0.  "
        "Use piping_min_wall_thickness to get the minimum wall thickness first, "
        "then call this tool to select the schedule — or use the schedule_recommended "
        "field that piping_min_wall_thickness already returns.  "
        "\n\nDISCLAIMER: ASME B31.1 methods — NOT ASME stamp certified."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nps_in": {
                "type": "number",
                "description": (
                    "Nominal pipe size (NPS) in inches.  "
                    "E.g. 6.0 for NPS 6, 4.0 for NPS 4.  "
                    "Supported: 0.5, 0.75, 1.0, 1.25, 1.5, 2.0, 2.5, 3.0, "
                    "4.0, 6.0, 8.0, 10.0, 12.0."
                ),
            },
            "min_thickness_in": {
                "type": "number",
                "description": (
                    "Minimum required wall thickness (inches).  "
                    "Use the ordered_min_thickness_in from piping_min_wall_thickness."
                ),
            },
        },
        "required": ["nps_in", "min_thickness_in"],
    },
)


async def run_piping_recommend_schedule(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.wall_thickness import recommend_schedule, _WALL_THICKNESS_IN
        import math

        nps_in = float(args["nps_in"])
        min_thickness_in = float(args["min_thickness_in"])

        schedule = recommend_schedule(nps_in, min_thickness_in)

        # Look up the actual wall for this NPS + schedule (if found)
        actual_wall = None
        if schedule not in ("NPS-NOT-FOUND", "EXCEEDS-XXS"):
            for (nps, sched), t in _WALL_THICKNESS_IN.items():
                if math.isclose(nps, nps_in, rel_tol=1e-4) and sched == schedule:
                    actual_wall = round(t, 4)
                    break

        payload: dict[str, Any] = {
            "ok": True,
            "nps_in": nps_in,
            "min_thickness_in": round(min_thickness_in, 5),
            "schedule_recommended": schedule,
            "actual_wall_in": actual_wall,
            "caveat": (
                "ASME B36.10M schedule lookup — NOT ASME stamp certified.  "
                "Review by a licensed Professional Engineer required before use."
            ),
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_SCHEDULE_ERROR")


# ---------------------------------------------------------------------------
# piping_pressure_drop  (Darcy-Weisbach + Crane TP-410 K-factors)
# ---------------------------------------------------------------------------

piping_pressure_drop_spec = ToolSpec(
    name="piping_pressure_drop",
    description=(
        "Calculate pipeline pressure drop for a multi-segment piping system "
        "using Darcy-Weisbach friction losses (Colebrook-White friction factor) "
        "and Crane TP-410 §3 K-factor fitting losses.  "
        "Returns total ΔP, straight-pipe contribution, fitting contribution, "
        "and per-segment / per-fitting breakdown.  "
        "\n\nMethod: Darcy-Weisbach ΔP = f·(L/D)·ρV²/2  (ASME B31 / Crane TP-410 §1). "
        "Friction factor from Colebrook-White iterative solver.  "
        "Fluid options: 'water' (60°F), 'oil' (SG≈0.85), 'air' (68°F), 'steam' (212°F).  "
        "\n\nFitting K keys: '90_elbow_welded', '45_elbow_welded', '90_elbow_threaded', "
        "'tee_through', 'tee_branch', 'gate_valve_open', 'globe_valve', 'check_valve', "
        "'ball_valve_open', 'butterfly_valve_open', 'angle_valve_open', "
        "'reducer_sudden', 'expander_sudden'.  "
        "\n\nDISCLAIMER: ASME B31 / Crane TP-410 methods — NOT certified compliance.  "
        "Review by a licensed engineer required."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "description": (
                    "List of straight pipe segments.  Each segment is an object with: "
                    "'diameter_in' (float, inside pipe diameter inches), "
                    "'length_ft' (float, segment length feet), "
                    "'roughness' (float, optional, wall roughness ft, default 0.00015), "
                    "'fluid' (string, optional, fluid override)."
                ),
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
            },
            "fittings": {
                "type": "array",
                "description": (
                    "List of fittings.  Each fitting is an object with: "
                    "'fitting_kind' (string, Crane TP-410 fitting key), "
                    "'diameter_in' (float, pipe diameter at fitting), "
                    "'quantity' (int, optional, default 1), "
                    "'beta' (float, optional, area ratio for reducer/expander)."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "fitting_kind": {"type": "string"},
                        "diameter_in":  {"type": "number"},
                        "quantity":     {"type": "integer"},
                        "beta":         {"type": "number"},
                    },
                    "required": ["fitting_kind", "diameter_in"],
                },
            },
            "flow_gpm": {
                "type": "number",
                "description": "Volumetric flow rate (US gallons per minute).",
            },
            "fluid": {
                "type": "string",
                "enum": ["water", "oil", "air", "steam"],
                "description": "Default fluid for all segments. Default 'water'.",
            },
        },
        "required": ["segments", "flow_gpm"],
    },
)


async def run_piping_pressure_drop(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.asme_pressure import compute_pipeline_pressure_drop

        segments = args["segments"]
        fittings = args.get("fittings", [])
        flow_gpm = float(args["flow_gpm"])
        fluid    = str(args.get("fluid", "water"))

        result = compute_pipeline_pressure_drop(
            segments=segments,
            fittings=fittings,
            flow_gpm=flow_gpm,
            fluid=fluid,
        )
        payload: dict[str, Any] = {"ok": True, **result}
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_PRESSURE_DROP_ERROR")


# ---------------------------------------------------------------------------
# piping_b16_fittings  (ASME B16.9/B16.5 fitting catalogue + BOM)
# ---------------------------------------------------------------------------

piping_b16_fittings_spec = ToolSpec(
    name="piping_b16_fittings",
    description=(
        "Return ASME B16.9 butt-weld fitting dimensions and ASME B16.5 flange "
        "pressure-temperature ratings for a piping route.  Generates a fitting "
        "bill of materials (BOM) with dimensions, weights, and standard references.  "
        "\n\nASME B16.9-2018 fittings: 90° LR elbows, 90° SR elbows, 45° elbows, "
        "equal tees, concentric reducers, caps.  "
        "\n\nASME B16.5-2017 flanges: Class 150/300/600/900/1500/2500 pressure-"
        "temperature ratings for Material Group 1.1 (carbon steel A105/A216 WCB).  "
        "\n\nReturns: BOM list with center-to-face dimensions, overall lengths, "
        "approximate weights, and flange rating (psi and bar).  "
        "\n\nDISCLAIMER: Dimensional data from ASME B16.9/B16.5 — "
        "NOT a replacement for the primary ASME standard."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "dn": {
                "type": "integer",
                "description": (
                    "Nominal pipe diameter (DN, mm) for standard fittings.  "
                    "E.g. 50, 100, 150, 200, 250, 300."
                ),
            },
            "elbows_90lr": {
                "type": "integer",
                "description": "Number of 90° long-radius elbows (ASME B16.9). Default 0.",
            },
            "elbows_90sr": {
                "type": "integer",
                "description": "Number of 90° short-radius elbows (ASME B16.9). Default 0.",
            },
            "elbows_45": {
                "type": "integer",
                "description": "Number of 45° long-radius elbows (ASME B16.9). Default 0.",
            },
            "tees_equal": {
                "type": "integer",
                "description": "Number of equal tees (ASME B16.9). Default 0.",
            },
            "reducers": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "description": (
                    "List of [dn_large, dn_small] reducer pairs.  "
                    "E.g. [[200, 150], [150, 100]] for two reducers."
                ),
            },
            "caps": {
                "type": "integer",
                "description": "Number of end caps (ASME B16.9). Default 0.",
            },
            "flange_class": {
                "type": "integer",
                "enum": [150, 300, 600, 900, 1500, 2500],
                "description": (
                    "ASME B16.5 flange class for rating lookup.  "
                    "Omit to skip flange rating."
                ),
            },
            "flanges": {
                "type": "integer",
                "description": "Number of flanges (ASME B16.5). Default 0.",
            },
            "temp_F": {
                "type": "number",
                "description": (
                    "Design temperature (°F) for flange derating.  "
                    "Default 100°F (ambient).  Range 100–800°F for Group 1.1."
                ),
            },
        },
        "required": ["dn"],
    },
)


async def run_piping_b16_fittings(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.b16_catalogue import select_fittings

        dn            = int(args["dn"])
        elbows_90lr   = int(args.get("elbows_90lr", 0))
        elbows_90sr   = int(args.get("elbows_90sr", 0))
        elbows_45     = int(args.get("elbows_45", 0))
        tees_equal    = int(args.get("tees_equal", 0))
        raw_reducers  = args.get("reducers", [])
        reducers      = [tuple(r) for r in raw_reducers] if raw_reducers else None
        caps          = int(args.get("caps", 0))
        flange_class  = int(args["flange_class"]) if args.get("flange_class") else None
        flanges       = int(args.get("flanges", 0))
        temp_F        = float(args.get("temp_F", 100.0))

        result = select_fittings(
            dn=dn,
            elbows_90lr=elbows_90lr,
            elbows_90sr=elbows_90sr,
            elbows_45=elbows_45,
            tees_equal=tees_equal,
            reducers=reducers,
            caps=caps,
            flange_class=flange_class,
            flanges=flanges,
            temp_F=temp_F,
        )
        payload: dict[str, Any] = {"ok": True, "dn": dn, **result}
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_B16_ERROR")


# ---------------------------------------------------------------------------
# piping_pipe_stress  (ASME B31.1 sustained + thermal + occasional)
# ---------------------------------------------------------------------------

piping_pipe_stress_spec = ToolSpec(
    name="piping_pipe_stress",
    description=(
        "ASME B31.1 / B31.3 pipe stress check for straight pipe runs.  "
        "Evaluates three load cases: sustained (pressure + dead weight), "
        "thermal expansion (fully-restrained axial), and optional occasional "
        "(wind / seismic).  "
        "\n\nSustained (B31.1 §104.8.1):  S_L = P·D/(4t) + M_gravity/Z ≤ S_h  "
        "\nThermal (fully restrained):     σ_th = E·α·ΔT  [reports force and stress] "
        "\nOccasional (B31.1 §104.8.4):   S_L_occ = S_sustained + M_occ/Z ≤ 1.33·S_h  "
        "\n\nMaterials: 'A106-B' (carbon steel), 'A53-B', 'A312-304', "
        "'A312-316', 'A333-6'.  "
        "\n\nDISCLAIMER: Simplified ASME B31 methods — NOT ASME stamp certified.  "
        "Full piping flexibility analysis (CAESAR II-class 3D elastic FEA) required "
        "for actual installation."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "od_in": {
                "type": "number",
                "description": "Pipe outside diameter (inches).",
            },
            "wall_in": {
                "type": "number",
                "description": "Nominal pipe wall thickness (inches).",
            },
            "pressure_psi": {
                "type": "number",
                "description": "Internal design gauge pressure (psi).",
            },
            "weight_lbf_per_ft": {
                "type": "number",
                "description": (
                    "Distributed weight of pipe + fluid + insulation (lbf/ft).  "
                    "Typical carbon steel 4\" Sch40 water-filled ≈ 15–20 lbf/ft."
                ),
            },
            "span_ft": {
                "type": "number",
                "description": (
                    "Support span length (feet) for gravity bending moment.  "
                    "Typical steam: 15–20 ft; water: 12–18 ft per ASME B31.1 Table 121.5."
                ),
            },
            "material": {
                "type": "string",
                "enum": ["A106-B", "A53-B", "A312-304", "A312-316", "A333-6"],
                "description": "Material key for allowable stress lookup. Default 'A106-B'.",
            },
            "code": {
                "type": "string",
                "enum": ["B31.1", "B31.3"],
                "description": "ASME piping code. Default 'B31.1'.",
            },
            "delta_T_F": {
                "type": "number",
                "description": (
                    "Temperature change ΔT (°F) from ambient to operating temperature.  "
                    "Used for thermal expansion force calculation.  Default 0 (no thermal)."
                ),
            },
            "M_occasional_inlbf": {
                "type": "number",
                "description": (
                    "Occasional load bending moment (in-lbf) from wind, seismic, etc.  "
                    "Omit (or 0) to skip occasional load check."
                ),
            },
            "joint_efficiency": {
                "type": "number",
                "description": (
                    "Longitudinal weld joint efficiency E.  "
                    "1.0 = seamless (default); 0.85 = ERW."
                ),
            },
        },
        "required": ["od_in", "wall_in", "pressure_psi", "weight_lbf_per_ft", "span_ft"],
    },
)


async def run_piping_pipe_stress(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.pipe_stress import (
            sustained_stress, thermal_expansion_force, occasional_stress_check,
            _pipe_section_modulus_in3,
        )

        od_in            = float(args["od_in"])
        wall_in          = float(args["wall_in"])
        pressure_psi     = float(args["pressure_psi"])
        weight_lbf_ft    = float(args["weight_lbf_per_ft"])
        span_ft          = float(args["span_ft"])
        material         = str(args.get("material", "A106-B"))
        code             = str(args.get("code", "B31.1"))
        delta_T_F        = float(args.get("delta_T_F", 0.0))
        M_occ            = float(args.get("M_occasional_inlbf", 0.0))
        joint_eff        = float(args.get("joint_efficiency", 1.0))

        # Sustained check
        sus = sustained_stress(
            od_in=od_in,
            wall_in=wall_in,
            pressure_psi=pressure_psi,
            weight_lbf_per_ft=weight_lbf_ft,
            span_ft=span_ft,
            material=material,
            code=code,
            joint_efficiency=joint_eff,
        )

        # Thermal check
        thermal = None
        if delta_T_F != 0.0:
            thermal = thermal_expansion_force(
                od_in=od_in,
                wall_in=wall_in,
                delta_T_F=delta_T_F,
                material=material,
                code=code,
            )

        # Occasional check
        occ = None
        if M_occ > 0.0:
            Z = _pipe_section_modulus_in3(od_in, wall_in)
            from kerf_piping.pipe_stress import _SH_PSI
            S_h = _SH_PSI.get(material, 17_500)
            occ = occasional_stress_check(
                S_sustained_psi=sus.calculated_psi,
                M_occasional_inlbf=M_occ,
                Z_in3=Z,
                S_h_psi=S_h,
            )

        payload: dict[str, Any] = {
            "ok": True,
            "material": material,
            "code": code,
            "od_in": od_in,
            "wall_in": wall_in,
            "sustained": sus.as_dict(),
            "thermal": thermal,
            "occasional": occ.as_dict() if occ else None,
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_STRESS_ERROR")


# ---------------------------------------------------------------------------
# piping_route_3d  — 3D intelligent piping route with AABB clash avoidance
# ---------------------------------------------------------------------------

piping_route_3d_spec = ToolSpec(
    name="piping_route_3d",
    description=(
        "Route a pipe in 3D between two nozzle/connection points using "
        "orthogonal (manhattan) segments.  Inserts 90° LR elbows at direction "
        "changes per ASME B16.9.  Supports spec-driven schedule selection "
        "(ASME B31.3 Barlow) and basic AABB obstacle clash avoidance.  "
        "Returns: 3D centreline waypoints, fitting counts, elbow centre-to-face "
        "dimension (ASME B16.9), total pipe length, and a fitting BOM.  "
        "\n\nAll positions in metres.  "
        "\n\nPipe spec presets: 'CS-A' (A106-B, Sch40, 10 barg), "
        "'CS-HH' (A106-B, Sch80, 40 barg), 'SS-316L' (A312-316L, Sch40, 10 barg).  "
        "\n\nDISCLAIMER: Routing is orthogonal only (no diagonal segments).  "
        "Interactive drag-routing and 3D plant model integration require the Kerf "
        "plant UI (not yet wired in production).  Clash avoidance is AABB-only.  "
        "For certified installation review by a licensed engineer is required."
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
            "dn": {
                "type": "integer",
                "description": (
                    "Nominal pipe diameter DN (mm).  "
                    "E.g. 25, 50, 80, 100, 150, 200, 250, 300.  Default 50."
                ),
            },
            "schedule": {
                "type": "string",
                "description": (
                    "Pipe schedule code.  E.g. '40', '80', 'STD', 'XS', '160'.  "
                    "Ignored if pipe_spec is provided (spec drives schedule)."
                ),
            },
            "pipe_spec": {
                "type": "string",
                "enum": ["CS-A", "CS-HH", "SS-316L", "API-X52"],
                "description": (
                    "Preset pipe class.  Drives schedule via ASME B31.3 Barlow.  "
                    "CS-A = A106-B Sch40 10barg; CS-HH = A106-B Sch80 40barg; "
                    "SS-316L = A312-316L Sch40 10barg; API-X52 = X52 STD 70barg."
                ),
            },
            "obstacles": {
                "type": "array",
                "description": (
                    "List of AABB obstacles to route around.  "
                    "Each obstacle: {'min': [x,y,z], 'max': [x,y,z], 'label': '...'}"
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "min": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "max": {
                            "type": "array",
                            "items": {"type": "number"},
                            "minItems": 3,
                            "maxItems": 3,
                        },
                        "label": {"type": "string"},
                    },
                    "required": ["min", "max"],
                },
            },
            "clearance_m": {
                "type": "number",
                "description": (
                    "Minimum clearance around obstacles (metres).  Default 0.3."
                ),
            },
            "prefer_axis": {
                "type": "string",
                "enum": ["Z", "X", "Y"],
                "description": (
                    "Which axis to travel first.  "
                    "'Z' = vertical first (typical piping convention).  Default 'Z'."
                ),
            },
        },
        "required": ["start", "end"],
    },
)


async def run_piping_route_3d(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.pid import Point3
        from kerf_piping.route3d import route_3d, AABB
        from kerf_piping.pipe_spec import (
            standard_class_cs_a, standard_class_cs_hh,
            standard_class_ss_316l, standard_class_api_x52,
        )

        start_raw = args["start"]
        end_raw   = args["end"]
        dn        = int(args.get("dn", 50))
        sched_str = str(args.get("schedule", "40"))
        spec_key  = args.get("pipe_spec")
        prefer    = str(args.get("prefer_axis", "Z"))
        clearance = float(args.get("clearance_m", 0.3))

        start = Point3(*[float(v) for v in start_raw])
        end   = Point3(*[float(v) for v in end_raw])

        # Resolve spec
        spec = None
        if spec_key:
            spec_map = {
                "CS-A":   standard_class_cs_a,
                "CS-HH":  standard_class_cs_hh,
                "SS-316L": standard_class_ss_316l,
                "API-X52": standard_class_api_x52,
            }
            builder = spec_map.get(spec_key)
            if builder:
                spec = builder()

        # Parse obstacles
        obs_raw = args.get("obstacles", [])
        obstacles = []
        for ob in obs_raw:
            obstacles.append(AABB(
                min_pt=tuple(float(v) for v in ob["min"]),
                max_pt=tuple(float(v) for v in ob["max"]),
                label=str(ob.get("label", "")),
            ))

        result = route_3d(
            start, end,
            dn=dn,
            spec=spec,
            schedule=sched_str if not spec else None,
            obstacles=obstacles,
            clearance_m=clearance,
            prefer_axis=prefer,
        )

        payload = result.as_dict()
        payload["ok"] = True
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_ROUTE_3D_ERROR")


# ---------------------------------------------------------------------------
# piping_catalogue_component  — ASME B16.9/B16.5 3D component catalogue
# ---------------------------------------------------------------------------

piping_catalogue_component_spec = ToolSpec(
    name="piping_catalogue_component",
    description=(
        "Look up a 3D piping component from the spec-driven ASME catalogue.  "
        "Returns: face geometry (nozzle positions + flow directions), "
        "face-to-face / centre-to-face dimensions per ASME B16.9 or B16.5, "
        "nominal OD, and a BOM line.  "
        "\n\nComponent types: "
        "'elbow_90_lr' (ASME B16.9 90° LR), "
        "'elbow_90_sr' (ASME B16.9 90° SR), "
        "'elbow_45_lr' (ASME B16.9 45° LR), "
        "'tee_equal' (ASME B16.9 equal tee), "
        "'reducer_concentric' (ASME B16.9 concentric reducer), "
        "'flange_weldneck' (ASME B16.5 weld-neck flange), "
        "'valve_gate' (gate valve, ASME B16.10), "
        "'valve_ball' (full-bore ball valve, API 6D), "
        "'cap' (ASME B16.9 end cap).  "
        "\n\nCommon DN values: 15, 20, 25, 32, 40, 50, 65, 80, 100, 150, 200, "
        "250, 300.  "
        "\n\nDISCLAIMER: Dimensional data from ASME B16.9-2018, B16.5-2017, "
        "B16.10-2000, API 6D-2021 — NOT a replacement for the primary standards.  "
        "For procurement and fabrication verify against the current ASME publication."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "component_type": {
                "type": "string",
                "enum": [
                    "elbow_90_lr",
                    "elbow_90_sr",
                    "elbow_45_lr",
                    "tee_equal",
                    "reducer_concentric",
                    "flange_weldneck",
                    "valve_gate",
                    "valve_ball",
                    "cap",
                ],
                "description": "Component type identifier.",
            },
            "dn": {
                "type": "integer",
                "description": (
                    "Nominal pipe diameter DN (mm).  "
                    "E.g. 25, 50, 80, 100, 150, 200."
                ),
            },
            "schedule": {
                "type": "string",
                "description": "Pipe schedule (e.g. '40', '80', 'STD').  Default '40'.",
            },
            "dn_branch": {
                "type": "integer",
                "description": (
                    "Branch / small-end DN (mm) for reducers or reducing tees.  "
                    "Required for 'reducer_concentric'."
                ),
            },
            "flange_class": {
                "type": "integer",
                "enum": [150, 300, 600, 900, 1500, 2500],
                "description": (
                    "ASME B16.5 flange class for 'flange_weldneck'.  Default 150."
                ),
            },
            "quantity": {
                "type": "integer",
                "description": "Quantity for BOM aggregation.  Default 1.",
            },
        },
        "required": ["component_type", "dn"],
    },
)


async def run_piping_catalogue_component(args: dict[str, Any], ctx: "ProjectCtx") -> str:
    try:
        from kerf_piping.route3d import catalogue_component

        comp_type   = str(args["component_type"])
        dn          = int(args["dn"])
        schedule    = str(args.get("schedule", "40"))
        dn_branch   = int(args["dn_branch"]) if args.get("dn_branch") else None
        flange_cls  = int(args["flange_class"]) if args.get("flange_class") else None
        quantity    = int(args.get("quantity", 1))

        comp = catalogue_component(
            comp_type, dn,
            schedule=schedule,
            dn_branch=dn_branch,
            flange_class=flange_cls,
        )

        payload = {
            "ok": True,
            **comp.as_dict(),
            "bom_line": comp.bom_line(quantity),
        }
        return ok_payload(payload)

    except Exception as exc:
        return err_payload(str(exc), "PIPING_CATALOGUE_ERROR")
