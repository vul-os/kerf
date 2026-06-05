"""
tools_corridor.py — LLM tools for corridor B-rep, volume, and IFC alignment (GK-P49).

Exposes:
  civil_corridor_brep        — Corridor.to_brep(): swept road solid
  civil_corridor_volume      — Corridor.volume(): pavement volume estimate
  civil_corridor_ifc_alignment — Corridor.ifc_alignment_dict()
"""
from __future__ import annotations

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_civil._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# Shared helper: build a Corridor from params
# ---------------------------------------------------------------------------

def _build_corridor(params: dict):
    from kerf_civil.horizontal_alignment import HorizontalAlignment
    from kerf_civil.vertical_alignment import VerticalAlignment
    from kerf_civil.corridor import TypicalSection, Corridor

    L = float(params.get("alignment_length_m", 200.0))
    grade = float(params.get("grade_pct", 0.0))
    datum = float(params.get("datum_elev_m", 0.0))

    ha = HorizontalAlignment()
    ha.add_tangent(L)

    va = VerticalAlignment()
    va.set_datum(elev=datum, grade_pct=grade)
    va.add_tangent(L)

    ts = TypicalSection(
        lane_width=float(params.get("lane_width_m", 3.65)),
        shoulder_width=float(params.get("shoulder_width_m", 2.4)),
        lanes_each_side=int(params.get("lanes_each_side", 1)),
        crown_slope_pct=float(params.get("crown_slope_pct", 2.0)),
        cut_slope=float(params.get("cut_slope", 2.0)),
        fill_slope=float(params.get("fill_slope", 2.0)),
    )

    return Corridor(h_alignment=ha, v_alignment=va, typical_section=ts)


# ---------------------------------------------------------------------------
# Tool: civil_corridor_brep
# ---------------------------------------------------------------------------

civil_corridor_brep_spec = ToolSpec(
    name="civil_corridor_brep",
    description=(
        "Build a swept B-rep Body representing a straight road corridor.  "
        "The body is constructed by sweeping a typical cross-section along "
        "the alignment at regular station intervals.  Returns body face count "
        "and shell statistics.\n"
        "\n"
        "Returns:\n"
        "  ok          : bool\n"
        "  face_count  : int\n"
        "  shell_count : int\n"
        "\n"
        "Errors: {ok:false, reason}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alignment_length_m": {
                "type": "number",
                "description": "Total alignment length (m).",
                "default": 200.0,
            },
            "interval_m": {
                "type": "number",
                "description": "Station interval for cross-sections (m).",
                "default": 20.0,
            },
            "lane_width_m": {"type": "number", "default": 3.65},
            "shoulder_width_m": {"type": "number", "default": 2.4},
            "lanes_each_side": {"type": "integer", "default": 1},
            "crown_slope_pct": {"type": "number", "default": 2.0},
            "grade_pct": {"type": "number", "default": 0.0},
            "datum_elev_m": {"type": "number", "default": 0.0},
            "cut_slope": {"type": "number", "default": 2.0},
            "fill_slope": {"type": "number", "default": 2.0},
        },
        "required": [],
    },
)


async def run_civil_corridor_brep(params: dict, ctx: "ProjectCtx") -> str:
    try:
        corridor = _build_corridor(params)
        interval = float(params.get("interval_m", 20.0))
        body = corridor.to_brep(interval=interval)

        face_count = 0
        shell_count = 0
        for shell in getattr(body, "shells", []):
            face_count += len(shell.faces)
            shell_count += 1
        for solid in getattr(body, "solids", []):
            for shell in solid.shells:
                face_count += len(shell.faces)
                shell_count += 1

        return ok_payload({
            "ok": True,
            "face_count": face_count,
            "shell_count": shell_count,
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_CORRIDOR_BREP_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_corridor_volume
# ---------------------------------------------------------------------------

civil_corridor_volume_spec = ToolSpec(
    name="civil_corridor_volume",
    description=(
        "Estimate the pavement volume (m³) for a road corridor using "
        "prismatoid integration over the swept cross-section.  Assumes 0.5 m "
        "combined pavement + base course depth.\n"
        "\n"
        "Returns:\n"
        "  ok       : bool\n"
        "  volume_m3: float\n"
        "\n"
        "Errors: {ok:false, reason}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alignment_length_m": {"type": "number", "default": 200.0},
            "interval_m": {"type": "number", "default": 20.0},
            "lane_width_m": {"type": "number", "default": 3.65},
            "shoulder_width_m": {"type": "number", "default": 2.4},
            "lanes_each_side": {"type": "integer", "default": 1},
            "crown_slope_pct": {"type": "number", "default": 2.0},
            "grade_pct": {"type": "number", "default": 0.0},
            "datum_elev_m": {"type": "number", "default": 0.0},
        },
        "required": [],
    },
)


async def run_civil_corridor_volume(params: dict, ctx: "ProjectCtx") -> str:
    try:
        corridor = _build_corridor(params)
        interval = float(params.get("interval_m", 20.0))
        vol = corridor.volume(interval=interval)

        return ok_payload({
            "ok": True,
            "volume_m3": round(vol, 4),
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_CORRIDOR_VOLUME_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_corridor_ifc_alignment
# ---------------------------------------------------------------------------

civil_corridor_ifc_alignment_spec = ToolSpec(
    name="civil_corridor_ifc_alignment",
    description=(
        "Return a minimal IfcAlignmentProduct dict for IFC export of a road "
        "corridor.  Includes total length, lane/shoulder widths, and slopes.\n"
        "\n"
        "Returns:\n"
        "  ok       : bool\n"
        "  ifc_dict : IfcAlignmentProduct dict\n"
        "\n"
        "Errors: {ok:false, reason}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alignment_length_m": {"type": "number", "default": 200.0},
            "lane_width_m": {"type": "number", "default": 3.65},
            "shoulder_width_m": {"type": "number", "default": 2.4},
            "lanes_each_side": {"type": "integer", "default": 1},
            "crown_slope_pct": {"type": "number", "default": 2.0},
            "grade_pct": {"type": "number", "default": 0.0},
            "datum_elev_m": {"type": "number", "default": 0.0},
            "cut_slope": {"type": "number", "default": 2.0},
            "fill_slope": {"type": "number", "default": 2.0},
        },
        "required": [],
    },
)


async def run_civil_corridor_ifc_alignment(params: dict, ctx: "ProjectCtx") -> str:
    try:
        corridor = _build_corridor(params)
        ifc = corridor.ifc_alignment_dict()

        return ok_payload({
            "ok": True,
            "ifc_dict": ifc,
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_CORRIDOR_IFC_ERROR")


# ---------------------------------------------------------------------------
# Tool: civil_corridor_model  (full template-driven corridor model)
# ---------------------------------------------------------------------------

civil_corridor_model_spec = ToolSpec(
    name="civil_corridor_model",
    description=(
        "Template-driven corridor model: sweeps a parametric road cross-section "
        "assembly (point-coded: CL, edge-lane, shoulder, optional ditch, "
        "cut/fill side-slopes) along a horizontal + vertical alignment, "
        "sampling stations at a specified interval.\n"
        "\n"
        "Standard methods:\n"
        "  • AASHTO Green Book cross-section design — lane widths (§2.2), "
        "shoulders (§2.3), normal crown (§4.2), side slopes (§3.3.2).\n"
        "  • Daylight-slope intersection: iterative stepping to find where the "
        "cut or fill slope meets the TIN terrain surface.\n"
        "  • Average-end-area earthwork volumes (AASHTO §2.2.3).\n"
        "  • Mass-haul (Brückner) curve with swell factor.\n"
        "\n"
        "Terrain points are supplied as a flat list of [x, y, z] triples "
        "(WGS84 metres or project CRS).  If omitted, daylight is placed at "
        "the shoulder hinge (flat-ground approximation).\n"
        "\n"
        "Returns:\n"
        "  ok              : bool\n"
        "  station_count   : int — number of cross-sections generated\n"
        "  cross_sections  : per-station list of {\n"
        "                      station_m, cl_elev_m, cut_area_m2, fill_area_m2,\n"
        "                      points: [{offset_m, elev_m, label}] }\n"
        "  earthwork       : {total_cut_m3, total_fill_m3, net_m3}\n"
        "  mass_haul       : [{station_m, mass_ordinate_m3, cut_vol_m3, fill_vol_m3}]\n"
        "  corridor_strings: {label: [[x,y,z], ...]} — 3-D feature-line strings\n"
        "\n"
        "Errors: {ok:false, reason}."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "alignment_length_m": {
                "type": "number",
                "description": "Total alignment length (m).",
                "default": 200.0,
            },
            "interval_m": {
                "type": "number",
                "description": "Station sampling interval (m).",
                "default": 20.0,
            },
            "grade_pct": {
                "type": "number",
                "description": "Constant vertical grade (%) for a simple uniform profile.",
                "default": 0.0,
            },
            "datum_elev_m": {
                "type": "number",
                "description": "Starting elevation at station 0 (m).",
                "default": 0.0,
            },
            "lane_width_m": {
                "type": "number",
                "description": "Single travel-lane width (m). AASHTO standard: 3.6–3.7 m.",
                "default": 3.65,
            },
            "shoulder_width_m": {
                "type": "number",
                "description": "Shoulder width (m).",
                "default": 2.4,
            },
            "lanes_each_side": {
                "type": "integer",
                "description": "Number of lanes each side of centreline.",
                "default": 1,
            },
            "crown_slope_pct": {
                "type": "number",
                "description": "Normal crown cross-slope (%). AASHTO §4.2: 1.5–2.0 %.",
                "default": 2.0,
            },
            "shoulder_slope_pct": {
                "type": "number",
                "description": "Shoulder cross-slope (%). AASHTO §2.3: 5–8 %.",
                "default": 5.0,
            },
            "cut_slope": {
                "type": "number",
                "description": "Cut backslope H:V (e.g. 2.0 = 2H:1V). AASHTO §3.3.2.",
                "default": 2.0,
            },
            "fill_slope": {
                "type": "number",
                "description": "Fill foreslope H:V. AASHTO §3.3.2.",
                "default": 2.0,
            },
            "ditch_width_m": {
                "type": "number",
                "description": "Roadside ditch bottom width (m). 0 = no ditch.",
                "default": 0.0,
            },
            "ditch_depth_m": {
                "type": "number",
                "description": "Ditch depth below shoulder break (m).",
                "default": 0.0,
            },
            "terrain_points": {
                "type": "array",
                "description": (
                    "Existing ground surface as [[x, y, z], ...] triples (m). "
                    "When supplied, daylight points are intersected against the "
                    "TIN and earthwork cut/fill volumes are computed. "
                    "Minimum 3 non-collinear points required."
                ),
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "default": [],
            },
            "swell_factor": {
                "type": "number",
                "description": "Soil swell factor for mass-haul (AASHTO typical = 1.25).",
                "default": 1.25,
            },
            "daylight_step_m": {
                "type": "number",
                "description": "Step size for daylight-slope search (m). Default 0.1.",
                "default": 0.1,
            },
        },
        "required": [],
    },
)


async def run_civil_corridor_model(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_civil.horizontal_alignment import HorizontalAlignment
        from kerf_civil.vertical_alignment import VerticalAlignment
        from kerf_civil.corridor import TypicalSection, Corridor

        L = float(params.get("alignment_length_m", 200.0))
        interval = float(params.get("interval_m", 20.0))
        grade = float(params.get("grade_pct", 0.0))
        datum = float(params.get("datum_elev_m", 0.0))
        swell = float(params.get("swell_factor", 1.25))
        step = float(params.get("daylight_step_m", 0.1))

        ha = HorizontalAlignment()
        ha.add_tangent(L)

        va = VerticalAlignment()
        va.set_datum(elev=datum, grade_pct=grade)
        va.add_tangent(L)

        ts = TypicalSection(
            lane_width=float(params.get("lane_width_m", 3.65)),
            shoulder_width=float(params.get("shoulder_width_m", 2.4)),
            lanes_each_side=int(params.get("lanes_each_side", 1)),
            crown_slope_pct=float(params.get("crown_slope_pct", 2.0)),
            shoulder_slope_pct=float(params.get("shoulder_slope_pct", 5.0)),
            cut_slope=float(params.get("cut_slope", 2.0)),
            fill_slope=float(params.get("fill_slope", 2.0)),
            ditch_width=float(params.get("ditch_width_m", 0.0)),
            ditch_depth=float(params.get("ditch_depth_m", 0.0)),
        )

        # Build optional TIN terrain
        terrain = None
        terrain_pts_raw = params.get("terrain_points", [])
        if terrain_pts_raw and len(terrain_pts_raw) >= 3:
            try:
                from kerf_civil.tin import build_tin
                terrain = build_tin(terrain_pts_raw)
            except Exception as _tin_exc:
                terrain = None  # degrade gracefully

        corridor = Corridor(
            h_alignment=ha,
            v_alignment=va,
            typical_section=ts,
            terrain=terrain,
            daylight_step_m=step,
        )

        # Cross-sections
        sections = corridor.cross_sections(interval)

        xs_out = []
        for xs in sections:
            xs_out.append({
                "station_m":    round(xs.station, 3),
                "cl_elev_m":    round(xs.cl_elevation, 4),
                "cut_area_m2":  round(xs.cut_area_m2, 4),
                "fill_area_m2": round(xs.fill_area_m2, 4),
                "points": [
                    {
                        "offset_m": round(float(pt.offset), 4),
                        "elev_m":   round(float(pt.elevation), 4),
                        "label":    pt.label,
                    }
                    for pt in xs.points
                ],
            })

        # Earthwork volumes (only meaningful with terrain)
        earthwork = corridor.earthwork_volumes(interval)

        # Mass haul
        mass_haul_list = corridor.mass_haul_data(interval, swell_factor=swell)

        # Corridor strings (feature-lines)
        strings_raw = corridor.corridor_strings(interval)
        corridor_strings = {
            lbl: [[round(float(x), 3), round(float(y), 3), round(float(z), 4)]
                  for x, y, z in pts]
            for lbl, pts in strings_raw.items()
        }

        return ok_payload({
            "ok": True,
            "station_count": len(xs_out),
            "cross_sections": xs_out,
            "earthwork": {
                "total_cut_m3":  earthwork["total_cut_m3"],
                "total_fill_m3": earthwork["total_fill_m3"],
                "net_m3":        earthwork["net_m3"],
            },
            "mass_haul": [
                {
                    "station_m":        m["station_m"],
                    "cut_vol_m3":       m["cut_vol_m3"],
                    "fill_vol_m3":      m["fill_vol_m3"],
                    "mass_ordinate_m3": m["mass_ordinate_m3"],
                }
                for m in mass_haul_list
            ],
            "corridor_strings": corridor_strings,
        })
    except Exception as exc:
        return err_payload(str(exc), "CIVIL_CORRIDOR_MODEL_ERROR")


# TOOLS list consumed by plugin
TOOLS = [
    ("civil_corridor_brep",          civil_corridor_brep_spec,          run_civil_corridor_brep),
    ("civil_corridor_volume",        civil_corridor_volume_spec,        run_civil_corridor_volume),
    ("civil_corridor_ifc_alignment", civil_corridor_ifc_alignment_spec, run_civil_corridor_ifc_alignment),
    ("civil_corridor_model",         civil_corridor_model_spec,         run_civil_corridor_model),
]
