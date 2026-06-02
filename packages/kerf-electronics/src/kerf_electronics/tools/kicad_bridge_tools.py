"""LLM tools for the KiCad round-trip bridge.

Tools
-----
elec_export_kicad      — Export a Kerf schematic/PCB layout to a KiCad project directory.
elec_import_kicad_pcb  — Import a routed *.kicad_pcb back into Kerf.
"""

from __future__ import annotations

import json
import os
from typing import Any

from kerf_electronics._compat import ToolSpec, err_payload, ok_payload, register


# ─── elec_export_kicad ───────────────────────────────────────────────────────

elec_export_kicad_spec = ToolSpec(
    name="elec_export_kicad",
    description=(
        "Export a Kerf schematic + PCB layout to a KiCad project directory "
        "(*.kicad_pro + *.kicad_sch + *.kicad_pcb). "
        "The exported .kicad_pcb has all component footprints placed but routes/tracks "
        "intentionally empty — open it in KiCad Pcbnew to perform interactive routing, "
        "then use elec_import_kicad_pcb to bring the routed result back into Kerf. "
        "Returns the paths to the three written files plus metadata (component count, "
        "net count, layer count)."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "circuit_json": {
                "type": "array",
                "description": (
                    "Parsed CircuitJSON array from the active board/schematic file. "
                    "Should contain source_component, source_net, source_trace, "
                    "and pcb_component entries."
                ),
                "items": {"type": "object"},
            },
            "output_dir": {
                "type": "string",
                "description": (
                    "Absolute or relative path to a directory where the KiCad project "
                    "files will be written.  The directory is created if it does not exist."
                ),
            },
            "stem": {
                "type": "string",
                "description": (
                    "Base filename stem for all three files (e.g. 'my_board' produces "
                    "my_board.kicad_pro, my_board.kicad_sch, my_board.kicad_pcb). "
                    "Defaults to 'board'."
                ),
            },
        },
        "required": ["circuit_json", "output_dir"],
    },
)


@register(elec_export_kicad_spec)
async def run_elec_export_kicad(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    circuit_json = a.get("circuit_json")
    if not isinstance(circuit_json, list):
        return err_payload("circuit_json must be an array", "BAD_ARGS")

    output_dir = a.get("output_dir")
    if not output_dir or not isinstance(output_dir, str):
        return err_payload("output_dir is required and must be a string", "BAD_ARGS")

    stem = a.get("stem", "board") or "board"

    try:
        from kerf_electronics.kicad_bridge import export_to_kicad_project
    except ImportError as e:
        return err_payload(f"kicad_bridge module unavailable: {e}", "IMPORT_ERROR")

    try:
        result = export_to_kicad_project(
            schematic=circuit_json,
            pcb_layout=circuit_json,
            output_dir=output_dir,
            stem=stem,
        )
    except Exception as e:
        return err_payload(f"KiCad export failed: {e}", "EXPORT_ERROR")

    return ok_payload({
        "pro_path": result.pro_path,
        "sch_path": result.sch_path,
        "pcb_path": result.pcb_path,
        "num_components": result.num_components,
        "num_nets": result.num_nets,
        "layer_count": result.layer_count,
        "caveat": result.caveat,
        "message": (
            f"Exported KiCad project to {output_dir!r}: "
            f"{result.num_components} component(s), {result.num_nets} net(s). "
            f"Open {result.pcb_path!r} in KiCad Pcbnew to route the board, "
            f"then call elec_import_kicad_pcb with the saved file path."
        ),
    })


# ─── elec_import_kicad_pcb ───────────────────────────────────────────────────

elec_import_kicad_pcb_spec = ToolSpec(
    name="elec_import_kicad_pcb",
    description=(
        "Import a routed *.kicad_pcb file back into Kerf after interactive routing in KiCad. "
        "Extracts all routed track segments, vias, and updated footprint positions. "
        "Returns structured routing data that Kerf's DRC, simulation, and fabrication "
        "tools can consume.  Use this after the user has finished routing in KiCad Pcbnew "
        "and saved the .kicad_pcb file."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pcb_path": {
                "type": "string",
                "description": (
                    "Path to the routed *.kicad_pcb file.  Must be an absolute path "
                    "or relative to the current working directory."
                ),
            },
        },
        "required": ["pcb_path"],
    },
)


@register(elec_import_kicad_pcb_spec)
async def run_elec_import_kicad_pcb(ctx: Any, args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    pcb_path = a.get("pcb_path")
    if not pcb_path or not isinstance(pcb_path, str):
        return err_payload("pcb_path is required and must be a string", "BAD_ARGS")

    if not os.path.isfile(pcb_path):
        return err_payload(f"file not found: {pcb_path!r}", "NOT_FOUND")

    try:
        from kerf_electronics.kicad_bridge import import_from_kicad_pcb
    except ImportError as e:
        return err_payload(f"kicad_bridge module unavailable: {e}", "IMPORT_ERROR")

    try:
        result = import_from_kicad_pcb(pcb_path)
    except Exception as e:
        return err_payload(f"KiCad import failed: {e}", "IMPORT_ERROR")

    # Serialise dataclasses to plain dicts for JSON output
    tracks_out = [
        {
            "net_name": t.net_name,
            "layer": t.layer,
            "layer_cj": t.layer_cj,
            "start_x": t.start_x,
            "start_y": t.start_y,
            "end_x": t.end_x,
            "end_y": t.end_y,
            "width": t.width,
        }
        for t in result.tracks
    ]
    vias_out = [
        {"net_name": v.net_name, "x": v.x, "y": v.y, "drill": v.drill, "size": v.size}
        for v in result.vias
    ]
    fps_out = [
        {
            "ref": fp.ref,
            "fp_name": fp.fp_name,
            "x": fp.x,
            "y": fp.y,
            "rotation": fp.rotation,
            "layer_kicad": fp.layer_kicad,
            "layer_cj": fp.layer_cj,
        }
        for fp in result.footprint_positions
    ]

    return ok_payload({
        "source_file": result.source_file,
        "num_tracks": len(result.tracks),
        "num_vias": len(result.vias),
        "num_footprints": len(result.footprint_positions),
        "net_names": result.net_names,
        "tracks": tracks_out,
        "vias": vias_out,
        "footprint_positions": fps_out,
        "caveat": result.caveat,
        "message": (
            f"Imported {len(result.tracks)} track(s), {len(result.vias)} via(s), "
            f"{len(result.footprint_positions)} footprint(s) from {pcb_path!r}. "
            "Pass 'tracks' and 'footprint_positions' to Kerf's DRC or fab tools."
        ),
    })


# ─── TOOLS registry (for legacy plugin loader) ────────────────────────────────

TOOLS = [
    ("elec_export_kicad",     elec_export_kicad_spec,     run_elec_export_kicad),
    ("elec_import_kicad_pcb", elec_import_kicad_pcb_spec, run_elec_import_kicad_pcb),
]
