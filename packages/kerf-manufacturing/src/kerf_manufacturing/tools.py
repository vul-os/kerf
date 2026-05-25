"""
LLM tool definitions for kerf-manufacturing.

Tools
-----
manufacturing_moldflow  — Hele-Shaw isothermal injection-moulding fill
                          simulation (v1: fill-time map, weld-line detection,
                          short-shot flag).
"""

from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_manufacturing._compat import ToolSpec, err_payload, ok_payload, ProjectCtx  # type: ignore[no-redef]


# ---------------------------------------------------------------------------
# manufacturing_moldflow
# ---------------------------------------------------------------------------

manufacturing_moldflow_spec = ToolSpec(
    name="manufacturing_moldflow",
    description=(
        "Run an injection-moulding fill simulation using the Hele-Shaw isothermal "
        "finite-element model.\n"
        "\n"
        "Accepts a triangular shell mesh (mid-plane representation), gate node, "
        "optional material card, and optional process conditions.  Returns the "
        "fill-time map at each node, weld-line edge predictions, short-shot flag, "
        "and fill fraction.\n"
        "\n"
        "Mesh format:\n"
        "  nodes     : [[x, y], …] or [[x, y, z], …] — node coordinates (metres)\n"
        "  triangles : [[i, j, k], …]            — 0-based node indices\n"
        "  thickness : float | [t0, …] per element — shell thickness (metres)\n"
        "\n"
        "Material (optional — defaults to ABS_GENERIC):\n"
        "  material_name : one of 'ABS', 'PP', 'PA6'\n"
        "\n"
        "Process conditions (all optional):\n"
        "  melt_temp_c         — melt temperature °C (default 230)\n"
        "  injection_pressure_bar — injection pressure bar (default 150)\n"
        "  max_fill_time_s     — max fill time seconds (default 5)\n"
        "\n"
        "Returns:\n"
        "  ok              : bool\n"
        "  n_nodes         : int\n"
        "  n_triangles     : int\n"
        "  fill_fraction   : float 0–1\n"
        "  short_shot      : bool\n"
        "  weld_line_count : int\n"
        "  fill_time_s     : list[float] — nodal fill time (seconds; inf = not filled)\n"
        "  weld_line_segments : list of [[x0,y0,z0],[x1,y1,z1]] mid-plane segments\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "nodes": {
                "type": "array",
                "description": "Node coordinates as [[x, y], …] or [[x, y, z], …] in metres.",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 3,
                },
                "minItems": 3,
            },
            "triangles": {
                "type": "array",
                "description": "Triangle connectivity as [[i, j, k], …] — 0-based indices.",
                "items": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 3,
                    "maxItems": 3,
                },
                "minItems": 1,
            },
            "thickness": {
                "description": "Element thickness(es) in metres.  Scalar applies to all elements (default 0.002 m = 2 mm).",
            },
            "gate_node": {
                "type": "integer",
                "description": "0-based node index of the injection gate.",
                "default": 0,
            },
            "material_name": {
                "type": "string",
                "enum": ["ABS", "PP", "PA6"],
                "description": "Material preset (default 'ABS').",
                "default": "ABS",
            },
            "melt_temp_c": {
                "type": "number",
                "description": "Melt temperature in °C (default 230).",
                "default": 230.0,
            },
            "injection_pressure_bar": {
                "type": "number",
                "description": "Injection pressure in bar (default 150).",
                "default": 150.0,
            },
            "max_fill_time_s": {
                "type": "number",
                "description": "Maximum fill time in seconds (default 5.0).",
                "default": 5.0,
            },
        },
        "required": ["nodes", "triangles"],
    },
)


async def run_manufacturing_moldflow(params: dict, ctx: "ProjectCtx") -> str:
    try:
        import math
        import numpy as np

        from kerf_manufacturing.moldflow import (
            ShellMesh, GateLocation, InjectionConditions, run_moldflow,
        )
        from kerf_manufacturing.moldflow.materials import (
            ABS_GENERIC, PP_GENERIC, PA6_GENERIC,
        )

        nodes = params.get("nodes")
        triangles = params.get("triangles")
        if not nodes or not triangles:
            return err_payload("nodes and triangles are required", "BAD_ARGS")

        # Build thickness array
        raw_thickness = params.get("thickness", 2.0)
        n_tri = len(triangles)
        if isinstance(raw_thickness, (int, float)):
            thickness = [float(raw_thickness)] * n_tri
        else:
            thickness = [float(t) for t in raw_thickness]
            if len(thickness) != n_tri:
                return err_payload(
                    f"thickness length {len(thickness)} != n_triangles {n_tri}",
                    "BAD_ARGS",
                )

        # Build ShellMesh (nodes in metres; 2-D [x,y] or 3-D [x,y,z])
        nodes_arr = np.array(nodes, dtype=float)
        tri_arr = np.array(triangles, dtype=np.int32)
        mesh = ShellMesh(
            nodes=nodes_arr,
            triangles=tri_arr,
            thickness=np.array(thickness, dtype=float),
        )

        # Gate
        gate_node = int(params.get("gate_node", 0))
        gate = GateLocation(node_index=gate_node)

        # Material
        material_name = str(params.get("material_name", "ABS")).upper()
        material_map = {"ABS": ABS_GENERIC, "PP": PP_GENERIC, "PA6": PA6_GENERIC}
        material = material_map.get(material_name, ABS_GENERIC)

        # Conditions
        melt_temp_c = float(params.get("melt_temp_c", 230.0))
        injection_bar = float(params.get("injection_pressure_bar", 150.0))
        max_fill_s = float(params.get("max_fill_time_s", 5.0))

        conditions = InjectionConditions(
            melt_temperature_k=melt_temp_c + 273.15,
            injection_pressure_pa=injection_bar * 1e5,
            max_fill_time_s=max_fill_s,
        )

        # Run simulation
        result = run_moldflow(mesh, gate, material=material, conditions=conditions)

        # Serialise fill_time (replace inf with null for JSON compatibility)
        fill_time_list = [
            None if math.isinf(ft) else round(float(ft), 6)
            for ft in result.fill_time
        ]

        # Serialise weld-line segments
        weld_segs = [
            [
                [round(float(c), 4) for c in seg[0]],
                [round(float(c), 4) for c in seg[1]],
            ]
            for seg in (result.weld_line_segments or [])
        ]

        return ok_payload({
            "ok": True,
            "n_nodes": int(mesh.n_nodes),
            "n_triangles": int(mesh.n_triangles),
            "fill_fraction": round(float(result.fill_fraction), 6),
            "short_shot": bool(result.short_shot),
            "weld_line_count": len(weld_segs),
            "fill_time_s": fill_time_list,
            "weld_line_segments": weld_segs,
        })

    except Exception as exc:
        return err_payload(str(exc), "MANUFACTURING_MOLDFLOW_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

TOOLS = [
    ("manufacturing_moldflow", manufacturing_moldflow_spec, run_manufacturing_moldflow),
]
