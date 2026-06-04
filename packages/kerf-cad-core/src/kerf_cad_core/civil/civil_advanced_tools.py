"""
kerf_cad_core.civil.civil_advanced_tools — LLM tool wrappers for civil TIN,
gravity pipe networks, and pressure pipe networks.

Registers six tools with the Kerf tool registry:

  tin_build           — Build constrained Delaunay TIN from survey points.
  tin_contours        — Extract contour polylines at regular intervals.
  tin_cut_fill        — Compute cut/fill volumes between two surfaces.
  gravity_pipe_analyze — Manning capacity analysis for gravity sewer/storm network.
  pressure_pipe_analyze — Hazen-Williams hydraulic analysis for pressure networks.
  hazen_williams_headloss — Single-pipe Hazen-Williams head loss (utility).

All tools are pure-Python + NumPy; no OCC dependency.
Errors returned as {ok: false, reason: '...'} — tools never raise.

Author: imranparuk
"""
from __future__ import annotations

import json
from dataclasses import asdict

from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
from kerf_core.utils.context import ProjectCtx  # noqa: F401

from kerf_cad_core.civil.tin_surface import (
    SurveyPoint,
    Breakline,
    build_tin_from_points,
    contour_lines,
    cut_fill_volume,
    add_point_dynamic,
)
from kerf_cad_core.civil.gravity_pipe_network import (
    GravityManhole,
    GravityPipe,
    GravityPipeNetwork,
    manning_full_flow_l_s,
    rational_method_runoff,
)
from kerf_cad_core.civil.pressure_pipe_network import (
    PressureJunction,
    PressurePipe,
    PressureReservoir,
    PressurePipeNetwork,
    hazen_williams_headloss_m,
)


# ---------------------------------------------------------------------------
# Tool: tin_build
# ---------------------------------------------------------------------------

_tin_build_spec = ToolSpec(
    name="tin_build",
    description=(
        "Build a constrained Delaunay Triangulated Irregular Network (TIN) from "
        "survey / topo points.\n\n"
        "The algorithm uses Bowyer-Watson incremental Delaunay triangulation "
        "(Bowyer 1981; Watson 1981) with optional breakline constraint enforcement "
        "(Chew 1989; Edelsbrunner 2001 §4).\n\n"
        "Returns triangle count, elevation range, and a summary suitable for "
        "subsequent tin_contours or tin_cut_fill calls.\n\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": (
                    "Survey points. Each: {point_id, x, y, elevation, description?}. "
                    "x=easting, y=northing, elevation=z (all metres). ≥ 3 required."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "point_id": {"type": "string"},
                        "x": {"type": "number"},
                        "y": {"type": "number"},
                        "elevation": {"type": "number"},
                        "description": {"type": "string"},
                    },
                    "required": ["point_id", "x", "y", "elevation"],
                },
            },
            "breaklines": {
                "type": "array",
                "description": (
                    "Optional breakline constraints. Each: "
                    "{breakline_id, points: [[x,y,z],...], kind: 'standard'|'wall'|'non_destructive'}."
                ),
                "items": {"type": "object"},
            },
        },
        "required": ["points"],
    },
)


@register(_tin_build_spec, write=False)
async def run_tin_build(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_pts = a.get("points", [])
    if not isinstance(raw_pts, list) or len(raw_pts) < 3:
        return err_payload("points must be a list of ≥ 3 survey point objects", "BAD_ARGS")

    survey_pts: list[SurveyPoint] = []
    for i, pt in enumerate(raw_pts):
        if not isinstance(pt, dict):
            return err_payload(f"points[{i}] must be an object", "BAD_ARGS")
        try:
            survey_pts.append(SurveyPoint(
                point_id=str(pt.get("point_id", f"P{i}")),
                x=float(pt["x"]),
                y=float(pt["y"]),
                elevation=float(pt["elevation"]),
                description=str(pt.get("description", "")),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"points[{i}]: {exc}", "BAD_ARGS")

    breaklines: list[Breakline] = []
    for i, bl in enumerate(a.get("breaklines") or []):
        if not isinstance(bl, dict):
            continue
        bl_pts = bl.get("points", [])
        bl_pts_tuples = []
        for bp in bl_pts:
            if isinstance(bp, (list, tuple)) and len(bp) >= 3:
                bl_pts_tuples.append((float(bp[0]), float(bp[1]), float(bp[2])))
        breaklines.append(Breakline(
            breakline_id=str(bl.get("breakline_id", f"BL{i}")),
            points=bl_pts_tuples,
            kind=str(bl.get("kind", "standard")),
        ))

    try:
        surface = build_tin_from_points(survey_pts, breaklines or None)
    except ValueError as exc:
        return err_payload(str(exc), "TIN_ERROR")

    payload = {
        "ok": True,
        "point_count": len(surface.points),
        "triangle_count": int(surface.triangles.shape[0]),
        "breakline_count": len(surface.breaklines),
        "min_elevation_m": round(surface.min_elevation, 4),
        "max_elevation_m": round(surface.max_elevation, 4),
        "elevation_range_m": round(surface.max_elevation - surface.min_elevation, 4),
    }
    return ok_payload(payload)


# ---------------------------------------------------------------------------
# Tool: tin_contours
# ---------------------------------------------------------------------------

_tin_contours_spec = ToolSpec(
    name="tin_contours",
    description=(
        "Extract contour polylines from a TIN surface at regular elevation intervals.\n\n"
        "Uses marching-triangles algorithm to produce closed/open contour segments "
        "at each elevation level.  Returns polylines as (x, y) coordinate lists.\n\n"
        "Reference: standard marching-triangles linear interpolation.\n\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "points": {
                "type": "array",
                "description": "Survey points (same format as tin_build).",
                "items": {"type": "object"},
            },
            "elevation_interval": {
                "type": "number",
                "description": "Contour interval in metres (default 1.0).",
            },
        },
        "required": ["points"],
    },
)


@register(_tin_contours_spec, write=False)
async def run_tin_contours(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_pts = a.get("points", [])
    if not isinstance(raw_pts, list) or len(raw_pts) < 3:
        return err_payload("points must be a list of ≥ 3 survey point objects", "BAD_ARGS")

    survey_pts: list[SurveyPoint] = []
    for i, pt in enumerate(raw_pts):
        try:
            survey_pts.append(SurveyPoint(
                point_id=str(pt.get("point_id", f"P{i}")),
                x=float(pt["x"]),
                y=float(pt["y"]),
                elevation=float(pt["elevation"]),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"points[{i}]: {exc}", "BAD_ARGS")

    interval = float(a.get("elevation_interval", 1.0))
    if interval <= 0:
        return err_payload("elevation_interval must be > 0", "BAD_ARGS")

    try:
        surface = build_tin_from_points(survey_pts)
        polys = contour_lines(surface, elevation_interval=interval)
    except (ValueError, Exception) as exc:
        return err_payload(str(exc), "CONTOUR_ERROR")

    payload = {
        "ok": True,
        "contour_count": len(polys),
        "elevation_interval_m": interval,
        "polylines": [
            [[round(x, 4), round(y, 4)] for x, y in poly]
            for poly in polys
        ],
    }
    return ok_payload(payload)


# ---------------------------------------------------------------------------
# Tool: tin_cut_fill
# ---------------------------------------------------------------------------

_tin_cut_fill_spec = ToolSpec(
    name="tin_cut_fill",
    description=(
        "Compute cut and fill volumes between an existing ground surface and a "
        "design surface using the prismoidal grid method.\n\n"
        "Positive net = net cut required; negative = net fill required.\n\n"
        "Reference: ASCE Manual 60 (1982) §5 — grid-method earthwork calculation.\n\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "existing_points": {
                "type": "array",
                "description": "Existing ground survey points (same format as tin_build).",
                "items": {"type": "object"},
            },
            "design_points": {
                "type": "array",
                "description": "Design surface survey points.",
                "items": {"type": "object"},
            },
            "grid_spacing_m": {
                "type": "number",
                "description": "Sampling grid size in metres (default 1.0).",
            },
        },
        "required": ["existing_points", "design_points"],
    },
)


@register(_tin_cut_fill_spec, write=False)
async def run_tin_cut_fill(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    def _parse_pts(raw: list, label: str) -> tuple[list[SurveyPoint], str | None]:
        if not isinstance(raw, list) or len(raw) < 3:
            return [], f"{label} must be a list of ≥ 3 point objects"
        pts = []
        for i, pt in enumerate(raw):
            try:
                pts.append(SurveyPoint(
                    point_id=str(pt.get("point_id", f"P{i}")),
                    x=float(pt["x"]),
                    y=float(pt["y"]),
                    elevation=float(pt["elevation"]),
                ))
            except (KeyError, TypeError, ValueError) as exc:
                return [], f"{label}[{i}]: {exc}"
        return pts, None

    existing_raw = a.get("existing_points", [])
    design_raw = a.get("design_points", [])

    existing_pts, err = _parse_pts(existing_raw, "existing_points")
    if err:
        return err_payload(err, "BAD_ARGS")
    design_pts, err = _parse_pts(design_raw, "design_points")
    if err:
        return err_payload(err, "BAD_ARGS")

    grid_spacing = float(a.get("grid_spacing_m", 1.0))

    try:
        srf_a = build_tin_from_points(existing_pts)
        srf_b = build_tin_from_points(design_pts)
        result = cut_fill_volume(srf_a, srf_b, grid_spacing_m=grid_spacing)
    except (ValueError, Exception) as exc:
        return err_payload(str(exc), "CUT_FILL_ERROR")

    result["ok"] = True
    return ok_payload(result)


# ---------------------------------------------------------------------------
# Tool: gravity_pipe_analyze
# ---------------------------------------------------------------------------

_gravity_spec = ToolSpec(
    name="gravity_pipe_analyze",
    description=(
        "Analyse a gravity sewer / storm drain network using Manning's equation.\n\n"
        "For each pipe computes: full-flow capacity, design flow, flow depth, "
        "velocity, capacity flag (>80%), and self-cleaning check (v ≥ 0.6 m/s).\n\n"
        "Manning's equation (ASCE Manual 60 §5; Mays 2011 §10.3):\n"
        "  Q = (1/n) · A · R^(2/3) · S^(1/2)\n"
        "  Full-pipe circular: Q = 0.3117/n · D^(8/3) · S^(1/2)\n\n"
        "Rational method (ASCE Manual 77 §3.2):\n"
        "  Q = C · i · A / 3600   [L/s, mm/hr, m²]\n\n"
        "Reference: ASCE Manual 60 (1982); ASCE Manual 77 (1992); Mays 2011.\n\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "manholes": {
                "type": "array",
                "description": (
                    "Manhole nodes. Each: {manhole_id, location:[x,y], "
                    "rim_elevation, invert_elevation, diameter_m?}."
                ),
                "items": {"type": "object"},
            },
            "pipes": {
                "type": "array",
                "description": (
                    "Pipe segments. Each: {pipe_id, from_manhole, to_manhole, "
                    "diameter_mm, material?, manning_n?, invert_drop_m, length_m?}."
                ),
                "items": {"type": "object"},
            },
            "drainage_areas": {
                "type": "object",
                "description": (
                    "Optional: {manhole_id: area_m2} — tributary drainage area "
                    "for rational-method design flow."
                ),
            },
            "design_flow_factor": {
                "type": "number",
                "description": "Peak flow safety factor (default 1.5).",
            },
            "runoff_coeff": {
                "type": "number",
                "description": "Rational method C coefficient (default 0.5).",
            },
            "rainfall_intensity_mm_hr": {
                "type": "number",
                "description": "Design storm intensity (mm/hr, default 50).",
            },
        },
        "required": ["manholes", "pipes"],
    },
)


@register(_gravity_spec, write=False)
async def run_gravity_pipe_analyze(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_mh = a.get("manholes", [])
    raw_pipes = a.get("pipes", [])

    if not isinstance(raw_mh, list) or len(raw_mh) < 1:
        return err_payload("manholes must be a non-empty list", "BAD_ARGS")
    if not isinstance(raw_pipes, list) or len(raw_pipes) < 1:
        return err_payload("pipes must be a non-empty list", "BAD_ARGS")

    manholes: list[GravityManhole] = []
    for i, m in enumerate(raw_mh):
        try:
            loc = m.get("location", [0, 0])
            manholes.append(GravityManhole(
                manhole_id=str(m["manhole_id"]),
                location=(float(loc[0]), float(loc[1])),
                rim_elevation=float(m["rim_elevation"]),
                invert_elevation=float(m["invert_elevation"]),
                diameter_m=float(m.get("diameter_m", 1.2)),
            ))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            return err_payload(f"manholes[{i}]: {exc}", "BAD_ARGS")

    pipes: list[GravityPipe] = []
    for i, p in enumerate(raw_pipes):
        try:
            pipes.append(GravityPipe(
                pipe_id=str(p["pipe_id"]),
                from_manhole=str(p["from_manhole"]),
                to_manhole=str(p["to_manhole"]),
                diameter_mm=float(p["diameter_mm"]),
                material=str(p.get("material", "PVC")),
                manning_n=float(p.get("manning_n", 0.011)),
                invert_drop_m=float(p.get("invert_drop_m", 0.0)),
                length_m=float(p.get("length_m", 100.0)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"pipes[{i}]: {exc}", "BAD_ARGS")

    drainage_areas: dict[str, float] = {}
    raw_da = a.get("drainage_areas") or {}
    if isinstance(raw_da, dict):
        for k, v in raw_da.items():
            try:
                drainage_areas[str(k)] = float(v)
            except (TypeError, ValueError):
                pass

    network = GravityPipeNetwork(
        manholes=manholes,
        pipes=pipes,
        drainage_area_m2=drainage_areas,
    )

    try:
        analyses = network.analyze(
            design_flow_factor=float(a.get("design_flow_factor", 1.5)),
            runoff_coeff=float(a.get("runoff_coeff", 0.5)),
            rainfall_intensity_mm_hr=float(a.get("rainfall_intensity_mm_hr", 50.0)),
        )
    except Exception as exc:
        return err_payload(str(exc), "ANALYSIS_ERROR")

    payload = {
        "ok": True,
        "pipe_count": len(analyses),
        "pipes": [r.to_dict() for r in analyses],
        "at_capacity_count": sum(1 for r in analyses if r.is_at_capacity),
        "not_self_cleaning_count": sum(1 for r in analyses if not r.is_self_cleaning),
    }
    return ok_payload(payload)


# ---------------------------------------------------------------------------
# Tool: pressure_pipe_analyze
# ---------------------------------------------------------------------------

_pressure_spec = ToolSpec(
    name="pressure_pipe_analyze",
    description=(
        "Analyse a pressurised water / fire protection pipe network using the "
        "Hardy-Cross loop method with Hazen-Williams head loss.\n\n"
        "Solves for junction pressures and pipe flows given reservoir supply heads "
        "and junction demands.\n\n"
        "Hazen-Williams (SI form, AWWA M22 §3; Mays 2011 §11.3):\n"
        "  hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)\n\n"
        "Typical C values: PE/PVC=130-150, DI=100, old steel=80.\n"
        "Minimum residual pressure for fire service: 14 m (20 psi) — AWWA M22 §5.\n\n"
        "Reference: Hardy-Cross 1936; AWWA M22 (1975); Wood 1981; Mays 2011 §11.\n\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "junctions": {
                "type": "array",
                "description": (
                    "Demand nodes. Each: {junction_id, location:[x,y,z], "
                    "demand_l_s?, elevation?}."
                ),
                "items": {"type": "object"},
            },
            "pipes": {
                "type": "array",
                "description": (
                    "Pipe segments. Each: {pipe_id, from_junction, to_junction, "
                    "diameter_mm, length_m, material?, hazen_williams_c?, "
                    "minor_loss_coeff?}."
                ),
                "items": {"type": "object"},
            },
            "reservoirs": {
                "type": "array",
                "description": (
                    "Supply / fixed-head nodes. Each: {reservoir_id, location:[x,y,z], "
                    "head} where head is piezometric elevation (m)."
                ),
                "items": {"type": "object"},
            },
            "max_iter": {
                "type": "integer",
                "description": "Hardy-Cross iteration limit (default 30).",
            },
            "tol": {
                "type": "number",
                "description": "Convergence tolerance in L/s (default 0.001).",
            },
        },
        "required": ["junctions", "pipes", "reservoirs"],
    },
)


@register(_pressure_spec, write=False)
async def run_pressure_pipe_analyze(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    raw_j = a.get("junctions", [])
    raw_p = a.get("pipes", [])
    raw_r = a.get("reservoirs", [])

    if not isinstance(raw_j, list):
        return err_payload("junctions must be a list", "BAD_ARGS")
    if not isinstance(raw_p, list) or len(raw_p) < 1:
        return err_payload("pipes must be a non-empty list", "BAD_ARGS")
    if not isinstance(raw_r, list) or len(raw_r) < 1:
        return err_payload("reservoirs must be a non-empty list (≥ 1 supply node)", "BAD_ARGS")

    junctions: list[PressureJunction] = []
    for i, j in enumerate(raw_j):
        try:
            loc = j.get("location", [0, 0, 0])
            loc_t = (float(loc[0]), float(loc[1]), float(loc[2]))
            junctions.append(PressureJunction(
                junction_id=str(j["junction_id"]),
                location=loc_t,
                demand_l_s=float(j.get("demand_l_s", 0.0)),
                elevation=float(j.get("elevation", loc_t[2])),
            ))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            return err_payload(f"junctions[{i}]: {exc}", "BAD_ARGS")

    pipes_obj: list[PressurePipe] = []
    for i, p in enumerate(raw_p):
        try:
            pipes_obj.append(PressurePipe(
                pipe_id=str(p["pipe_id"]),
                from_junction=str(p["from_junction"]),
                to_junction=str(p["to_junction"]),
                diameter_mm=float(p["diameter_mm"]),
                length_m=float(p["length_m"]),
                material=str(p.get("material", "PVC")),
                hazen_williams_c=float(p.get("hazen_williams_c", 130.0)),
                minor_loss_coeff=float(p.get("minor_loss_coeff", 0.0)),
            ))
        except (KeyError, TypeError, ValueError) as exc:
            return err_payload(f"pipes[{i}]: {exc}", "BAD_ARGS")

    reservoirs: list[PressureReservoir] = []
    for i, r in enumerate(raw_r):
        try:
            loc = r.get("location", [0, 0, 0])
            reservoirs.append(PressureReservoir(
                reservoir_id=str(r["reservoir_id"]),
                location=(float(loc[0]), float(loc[1]), float(loc[2])),
                head=float(r["head"]),
            ))
        except (KeyError, TypeError, ValueError, IndexError) as exc:
            return err_payload(f"reservoirs[{i}]: {exc}", "BAD_ARGS")

    network = PressurePipeNetwork(
        junctions=junctions,
        pipes=pipes_obj,
        reservoirs=reservoirs,
    )

    try:
        results = network.hydraulic_analysis(
            max_iter=int(a.get("max_iter", 30)),
            tol=float(a.get("tol", 1e-3)),
        )
    except Exception as exc:
        return err_payload(str(exc), "ANALYSIS_ERROR")

    low_pressure = [r.junction_id for r in results if r.pressure_m < 14.0]  # AWWA M22 §5

    payload = {
        "ok": True,
        "junction_count": len(results),
        "junctions": [r.to_dict() for r in results],
        "low_pressure_junctions": low_pressure,   # < 14 m = < 20 psi
    }
    return ok_payload(payload)


# ---------------------------------------------------------------------------
# Tool: hazen_williams_headloss
# ---------------------------------------------------------------------------

_hw_spec = ToolSpec(
    name="hazen_williams_headloss",
    description=(
        "Compute Hazen-Williams head loss for a single pipe.\n\n"
        "SI formula (AWWA M22 §3; Mays 2011 Eq. 11.7):\n"
        "  hf = 10.67 · L · Q^1.852 / (C^1.852 · D^4.87)\n\n"
        "where Q is in m³/s, D in m, L in m.\n\n"
        "Typical C values:\n"
        "  PE/PVC = 130-150\n"
        "  Ductile iron = 100\n"
        "  Old steel = 80\n\n"
        "Reference: Hazen & Williams 1905; AWWA M22 (1975); Mays 2011 §11.3.\n\n"
        "Errors returned as {ok: false, reason: '...'}. Never raises."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "flow_l_s": {
                "type": "number",
                "description": "Flow rate in L/s (> 0).",
            },
            "diameter_mm": {
                "type": "number",
                "description": "Internal pipe diameter (mm, > 0).",
            },
            "length_m": {
                "type": "number",
                "description": "Pipe length (m, > 0).",
            },
            "hw_c": {
                "type": "number",
                "description": "Hazen-Williams C factor (e.g. 130 for PVC, 100 for DI).",
            },
        },
        "required": ["flow_l_s", "diameter_mm", "length_m", "hw_c"],
    },
)


@register(_hw_spec, write=False)
async def run_hazen_williams_headloss(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    flow_l_s = a.get("flow_l_s")
    diameter_mm = a.get("diameter_mm")
    length_m = a.get("length_m")
    hw_c = a.get("hw_c")

    for name, val in [("flow_l_s", flow_l_s), ("diameter_mm", diameter_mm),
                      ("length_m", length_m), ("hw_c", hw_c)]:
        if val is None:
            return err_payload(f"{name} is required", "BAD_ARGS")

    try:
        flow_l_s = float(flow_l_s)
        diameter_mm = float(diameter_mm)
        length_m = float(length_m)
        hw_c = float(hw_c)
    except (TypeError, ValueError) as exc:
        return err_payload(f"numeric parse error: {exc}", "BAD_ARGS")

    if flow_l_s <= 0:
        return err_payload("flow_l_s must be > 0", "BAD_ARGS")
    if diameter_mm <= 0:
        return err_payload("diameter_mm must be > 0", "BAD_ARGS")
    if length_m <= 0:
        return err_payload("length_m must be > 0", "BAD_ARGS")
    if hw_c <= 0:
        return err_payload("hw_c must be > 0", "BAD_ARGS")

    hf = hazen_williams_headloss_m(flow_l_s, diameter_mm, length_m, hw_c)
    velocity = (flow_l_s / 1000.0) / (3.14159265 * (diameter_mm / 1000.0) ** 2 / 4.0)

    payload = {
        "ok": True,
        "headloss_m": round(hf, 4),
        "slope_m_per_100m": round(hf / length_m * 100.0, 4),
        "velocity_m_s": round(velocity, 4),
        "flow_l_s": flow_l_s,
        "diameter_mm": diameter_mm,
        "length_m": length_m,
        "hw_c": hw_c,
    }
    return ok_payload(payload)
