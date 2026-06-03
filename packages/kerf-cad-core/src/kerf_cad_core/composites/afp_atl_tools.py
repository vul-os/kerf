"""
kerf_cad_core.composites.afp_atl_tools — LLM tool wrappers for AFP/ATL composite manufacturing.

Registers three tools with the Kerf tool registry:

  composites_generate_afp_paths    — generate parallel fiber paths for AFP/ATL layup
  composites_export_apt_cl         — export AFP program as APT CL file
  composites_laser_projection      — generate laser projection template
  composites_develop_flat_pattern  — develop 3-D ply boundary to flat 2-D pattern
  composites_export_flat_dxf       — export flat pattern as DXF R12

All tools are pure-Python; no OCC dependency.
Errors returned as {ok: false, reason: "..."} — tools never raise.

References
----------
Lopes, C.S. et al. (2010). Composites Part A, 41(6), 796–805.
Aligned Vision LPS5 User Manual (public).
Virtek IRIS 5D Operator's Guide (public).
AIA NAS 9300 Vol. III — APT Language.

Wave 9D: FiberSim AFP/ATL composite paths + laser projection

Author: imranparuk
"""
from __future__ import annotations

import json
from typing import Any

from kerf_cad_core._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx

from kerf_cad_core.composites.afp_atl_path import (
    CompositePlyDef,
    AfpAtlMachineSpec,
    generate_afp_paths,
    export_apt_cl_file,
)
from kerf_cad_core.composites.laser_projection import (
    LaserProjectorSpec,
    generate_laser_projection,
    export_virtek_als,
    export_aligned_vision_hfl,
)
from kerf_cad_core.composites.flat_pattern_export import (
    develop_ply_to_flat,
    export_flat_pattern_dxf,
)


# ---------------------------------------------------------------------------
# Helper: build CompositePlyDef from dict
# ---------------------------------------------------------------------------

def _ply_from_dict(d: dict) -> CompositePlyDef:
    """Parse a CompositePlyDef from a JSON-decoded dict."""
    return CompositePlyDef(
        ply_id=str(d.get("ply_id", "PLY-001")),
        ply_orientation_deg=float(d.get("ply_orientation_deg", 0.0)),
        material=str(d.get("material", "IM7/8552")),
        thickness_mm=float(d.get("thickness_mm", 0.125)),
        boundary_3d=[tuple(pt) for pt in d.get("boundary_3d", [])],  # type: ignore[misc]
    )


def _machine_from_dict(d: dict) -> AfpAtlMachineSpec:
    return AfpAtlMachineSpec(
        name=str(d.get("name", "Coriolis C1")),
        tape_width_mm=float(d.get("tape_width_mm", 12.7)),
        head_count=int(d.get("head_count", 8)),
        max_lay_rate_m_per_min=float(d.get("max_lay_rate_m_per_min", 30.0)),
    )


def _projector_from_dict(d: dict) -> LaserProjectorSpec:
    pos = d.get("position", [0.0, 0.0, 3.0])
    aim = d.get("aim_direction", [0.0, 0.0, -1.0])
    fov = d.get("fov_deg", [30.0, 20.0])
    return LaserProjectorSpec(
        name=str(d.get("name", "Virtek IRIS 5D")),
        position=(float(pos[0]), float(pos[1]), float(pos[2])),
        aim_direction=(float(aim[0]), float(aim[1]), float(aim[2])),
        fov_deg=(float(fov[0]), float(fov[1])),
        range_m=float(d.get("range_m", 4.0)),
    )


# ---------------------------------------------------------------------------
# Tool: composites_generate_afp_paths
# ---------------------------------------------------------------------------

_gen_afp_spec = ToolSpec(
    name="composites_generate_afp_paths",
    description=(
        "Generate parallel AFP/ATL (Automated Fiber Placement / Automated Tape Laying) "
        "fiber paths for a composite ply over a mold surface.\n"
        "\n"
        "Produces straight parallel tape courses at the ply orientation angle. "
        "Returns path count, total length, estimated lay time, coverage %, and waste %.\n"
        "\n"
        "HONEST limitation: straight parallel paths only — no variable-angle steered fibers.\n"
        "\n"
        "Reference: Lopes et al. (2010) Composites Part A 41(6):796-805."
    ),
    input_schema={
        "type": "object",
        "required": ["ply", "machine"],
        "properties": {
            "ply": {
                "type": "object",
                "description": "Ply definition (ply_id, ply_orientation_deg, material, thickness_mm, boundary_3d).",
                "properties": {
                    "ply_id": {"type": "string"},
                    "ply_orientation_deg": {"type": "number"},
                    "material": {"type": "string"},
                    "thickness_mm": {"type": "number"},
                    "boundary_3d": {"type": "array", "items": {"type": "array"}},
                },
            },
            "machine": {
                "type": "object",
                "description": "AFP/ATL machine spec (name, tape_width_mm, head_count, max_lay_rate_m_per_min).",
                "properties": {
                    "name": {"type": "string"},
                    "tape_width_mm": {"type": "number"},
                    "head_count": {"type": "integer"},
                    "max_lay_rate_m_per_min": {"type": "number"},
                },
            },
        },
    },
)


@register(_gen_afp_spec, write=False)
async def run_composites_generate_afp_paths(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        ply = _ply_from_dict(a.get("ply", {}))
        machine = _machine_from_dict(a.get("machine", {}))
        program = generate_afp_paths(ply, machine)
        return ok_payload({
            "path_count": len(program.paths),
            "total_length_m": program.total_length_m,
            "estimated_time_min": program.estimated_time_min,
            "head_count_used": program.head_count_used,
            "coverage_pct": program.coverage_pct,
            "waste_pct": program.waste_pct,
        })
    except Exception as exc:
        return err_payload(str(exc), "AFP_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_export_apt_cl
# ---------------------------------------------------------------------------

_apt_cl_spec = ToolSpec(
    name="composites_export_apt_cl",
    description=(
        "Export an AFP/ATL layup program as an APT CL (Cutter Location) file.\n"
        "\n"
        "APT CL is the legacy NC format for composite AFP/ATL machines (AIA NAS 9300 Vol. III).\n"
        "The output contains GOTO commands for each tape course.\n"
        "\n"
        "Provide a ply and machine; the function first generates the paths then serialises them."
    ),
    input_schema={
        "type": "object",
        "required": ["ply", "machine"],
        "properties": {
            "ply": {"type": "object", "description": "Ply definition dict."},
            "machine": {"type": "object", "description": "Machine spec dict."},
        },
    },
)


@register(_apt_cl_spec, write=False)
async def run_composites_export_apt_cl(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        ply = _ply_from_dict(a.get("ply", {}))
        machine = _machine_from_dict(a.get("machine", {}))
        program = generate_afp_paths(ply, machine)
        cl_text = export_apt_cl_file(program)
        return ok_payload({"cl_file": cl_text, "course_count": len(program.paths)})
    except Exception as exc:
        return err_payload(str(exc), "APT_CL_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_laser_projection
# ---------------------------------------------------------------------------

_laser_spec = ToolSpec(
    name="composites_laser_projection",
    description=(
        "Generate a laser projection template for composite ply layup guidance.\n"
        "\n"
        "Projects 3-D ply boundaries into the laser projector's coordinate frame and "
        "outputs a Virtek IRIS ALS XML or Aligned Vision HFL file for the laser system.\n"
        "\n"
        "References: Aligned Vision LPS5 User Manual; Virtek IRIS 5D Operator's Guide."
    ),
    input_schema={
        "type": "object",
        "required": ["plies", "projector"],
        "properties": {
            "plies": {
                "type": "array",
                "items": {"type": "object"},
                "description": "List of ply definition dicts.",
            },
            "projector": {
                "type": "object",
                "description": "Laser projector spec (name, position, aim_direction, fov_deg, range_m).",
            },
            "output_format": {
                "type": "string",
                "enum": ["virtek_als", "aligned_vision_hfl"],
                "description": "Output format. Default: virtek_als.",
            },
        },
    },
)


@register(_laser_spec, write=False)
async def run_composites_laser_projection(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        plies = [_ply_from_dict(p) for p in a.get("plies", [])]
        projector = _projector_from_dict(a.get("projector", {}))
        fmt = a.get("output_format", "virtek_als")
        proj_file = generate_laser_projection(plies, projector)
        if fmt == "aligned_vision_hfl":
            content = export_aligned_vision_hfl(proj_file)
            file_format = "HFL"
        else:
            content = export_virtek_als(proj_file)
            file_format = "ALS_XML"
        return ok_payload({
            "file_content": content,
            "file_format": file_format,
            "segment_count": len(proj_file.template_segments),
        })
    except Exception as exc:
        return err_payload(str(exc), "LASER_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_develop_flat_pattern
# ---------------------------------------------------------------------------

_flat_spec = ToolSpec(
    name="composites_develop_flat_pattern",
    description=(
        "Develop (unfold) a 3-D composite ply boundary to a 2-D flat pattern.\n"
        "\n"
        "Uses isometric projection for planar surfaces (exact), LSCM for non-developable "
        "surfaces (conformal approximation).  Returns the 2-D outline, fiber direction, "
        "nesting efficiency, and maximum distortion in mm.\n"
        "\n"
        "Reference: Lévy et al. (2002) SIGGRAPH, pp. 362-371."
    ),
    input_schema={
        "type": "object",
        "required": ["ply"],
        "properties": {
            "ply": {"type": "object", "description": "Ply definition dict."},
        },
    },
)


@register(_flat_spec, write=False)
async def run_composites_develop_flat_pattern(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        ply = _ply_from_dict(a.get("ply", {}))
        result = develop_ply_to_flat(ply)
        return ok_payload({
            "ply_id": result.ply_id,
            "flat_boundary_2d": result.flat_boundary_2d,
            "fiber_direction_in_flat": result.fiber_direction_in_flat,
            "nesting_efficiency_pct": result.nesting_efficiency_pct,
            "distortion_max_mm": result.distortion_max_mm,
        })
    except Exception as exc:
        return err_payload(str(exc), "FLAT_PATTERN_ERROR")


# ---------------------------------------------------------------------------
# Tool: composites_export_flat_dxf
# ---------------------------------------------------------------------------

_dxf_spec = ToolSpec(
    name="composites_export_flat_dxf",
    description=(
        "Export a flat-pattern ply outline as an AutoCAD DXF R12 file.\n"
        "\n"
        "First develops the 3-D ply boundary to 2-D, then exports LINE entities "
        "and a fiber-direction indicator in DXF R12 (AC1009) format.\n"
        "\n"
        "Reference: AutoCAD DXF Reference Release 12."
    ),
    input_schema={
        "type": "object",
        "required": ["ply"],
        "properties": {
            "ply": {"type": "object", "description": "Ply definition dict."},
        },
    },
)


@register(_dxf_spec, write=False)
async def run_composites_export_flat_dxf(ctx: ProjectCtx, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as exc:
        return err_payload(f"invalid args JSON: {exc}", "BAD_ARGS")

    try:
        ply = _ply_from_dict(a.get("ply", {}))
        flat_result = develop_ply_to_flat(ply)
        dxf_content = export_flat_pattern_dxf(flat_result)
        return ok_payload({
            "dxf_content": dxf_content,
            "vertex_count": len(flat_result.flat_boundary_2d),
            "nesting_efficiency_pct": flat_result.nesting_efficiency_pct,
        })
    except Exception as exc:
        return err_payload(str(exc), "DXF_EXPORT_ERROR")
