"""
LLM tool definitions for kerf-manufacturing.

Tools
-----
manufacturing_moldflow       — Hele-Shaw isothermal injection-moulding fill
                               simulation (v1: fill-time map, weld-line detection,
                               short-shot flag).
manufacturing_optimize_feed  — CAM feed-rate optimizer: compute recommended feed
                               per segment from chip-load model + machine dynamics
                               + tool deflection (Altintas 2012).
manufacturing_cycle_time     — Estimate CNC cycle time from an optimized toolpath.
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
# manufacturing_optimize_feed
# ---------------------------------------------------------------------------

manufacturing_optimize_feed_spec = ToolSpec(
    name="manufacturing_optimize_feed",
    description=(
        "Optimize the CNC feed rate for each segment of a toolpath using chip-load "
        "theory (Altintas 2012 Table 3.1), machine acceleration limits (Altintas §3.6), "
        "and tool deflection (Euler-Bernoulli cantilever model).\n"
        "\n"
        "DISCLAIMER: Reference values are from Altintas 2012 — NOT cutting-tool-"
        "manufacturer-certified.  Always verify with your tool supplier.\n"
        "\n"
        "toolpath_segments : list of segment dicts, each with:\n"
        "  length_mm       : float — segment length (mm)\n"
        "  doc_mm          : float — axial depth of cut (mm)\n"
        "  woc_mm          : float — radial width of cut (mm)\n"
        "  feed_override   : float (optional) — manual feed override (mm/min)\n"
        "\n"
        "material : str — work material: 'aluminum', 'steel', 'stainless',\n"
        "                 'cast_iron', 'plastic', 'titanium', 'brass', 'copper'\n"
        "\n"
        "tool : dict —\n"
        "  kind          : str   — 'hss'|'carbide'|'carbide_uncoated'|'ceramic'|'cermet'\n"
        "  diameter_mm   : float\n"
        "  n_flutes      : int   (optional)\n"
        "  overhang_mm   : float (optional — cantilever length for deflection cap)\n"
        "  e_gpa         : float (optional — tool Young's modulus; default 620 GPa carbide)\n"
        "\n"
        "dynamic_limits : dict —\n"
        "  max_feed_mm_min   : float — absolute feed cap (mm/min)\n"
        "  max_accel_mm_s2   : float — max table acceleration (mm/s²)\n"
        "  jerk_limit_mm_s3  : float (optional)\n"
        "\n"
        "Returns list of objects, one per segment:\n"
        "  segment_id         : int\n"
        "  length_mm          : float\n"
        "  base_feed_mm_min   : float — chip-load feed before dynamic caps\n"
        "  feed_mm_min        : float — final optimized feed\n"
        "  cap_reason         : str   — 'nominal'|'acceleration'|'deflection'|'override'\n"
        "  mrr_mm3_per_min    : float — material removal rate\n"
        "  doc_mm             : float\n"
        "  woc_mm             : float\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "toolpath_segments": {
                "type": "array",
                "description": "List of toolpath segment descriptors.",
                "items": {
                    "type": "object",
                    "properties": {
                        "length_mm": {"type": "number"},
                        "doc_mm": {"type": "number"},
                        "woc_mm": {"type": "number"},
                        "feed_override": {"type": "number"},
                    },
                    "required": ["length_mm", "doc_mm", "woc_mm"],
                },
                "minItems": 1,
            },
            "material": {
                "type": "string",
                "description": (
                    "Work material: 'aluminum', 'steel', 'stainless', 'cast_iron', "
                    "'plastic', 'titanium', 'brass', 'copper'."
                ),
            },
            "tool": {
                "type": "object",
                "description": "Tool descriptor (kind, diameter_mm, n_flutes, overhang_mm, e_gpa).",
                "properties": {
                    "kind": {"type": "string"},
                    "diameter_mm": {"type": "number"},
                    "n_flutes": {"type": "integer"},
                    "overhang_mm": {"type": "number"},
                    "e_gpa": {"type": "number"},
                },
                "required": ["kind", "diameter_mm"],
            },
            "dynamic_limits": {
                "type": "object",
                "description": "Machine dynamic limits.",
                "properties": {
                    "max_feed_mm_min": {"type": "number", "default": 10000.0},
                    "max_accel_mm_s2": {"type": "number", "default": 500.0},
                    "jerk_limit_mm_s3": {"type": "number"},
                },
            },
        },
        "required": ["toolpath_segments", "material", "tool"],
    },
)


async def run_manufacturing_optimize_feed(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_manufacturing.feed_rate import optimize_toolpath_feed

        segments = params.get("toolpath_segments")
        if not segments:
            return err_payload("toolpath_segments is required and must be non-empty", "BAD_ARGS")

        material = params.get("material")
        if not material:
            return err_payload("material is required", "BAD_ARGS")

        tool = params.get("tool")
        if not tool:
            return err_payload("tool is required", "BAD_ARGS")

        dynamic_limits = params.get("dynamic_limits") or {}

        result = optimize_toolpath_feed(
            toolpath_segments=segments,
            material=material,
            tool=tool,
            dynamic_limits=dynamic_limits,
        )

        return ok_payload({
            "ok": True,
            "n_segments": len(result),
            "segments": [
                {
                    "segment_id": s.segment_id,
                    "length_mm": s.length_mm,
                    "base_feed_mm_min": s.base_feed_mm_min,
                    "feed_mm_min": s.feed_mm_min,
                    "cap_reason": s.cap_reason,
                    "mrr_mm3_per_min": s.mrr_mm3_per_min,
                    "doc_mm": s.doc_mm,
                    "woc_mm": s.woc_mm,
                }
                for s in result
            ],
            "disclaimer": (
                "Altintas 2012 Table 3.1 reference data — "
                "NOT cutting-tool-manufacturer-certified."
            ),
        })

    except ValueError as exc:
        return err_payload(str(exc), "BAD_ARGS")
    except Exception as exc:
        return err_payload(str(exc), "MANUFACTURING_OPTIMIZE_FEED_ERROR")


# ---------------------------------------------------------------------------
# manufacturing_cycle_time
# ---------------------------------------------------------------------------

manufacturing_cycle_time_spec = ToolSpec(
    name="manufacturing_cycle_time",
    description=(
        "Estimate the total CNC cycle time (seconds) from an optimized toolpath "
        "produced by manufacturing_optimize_feed, or from any list of segments "
        "with length_mm and feed_mm_min fields.\n"
        "\n"
        "Formula: t = Σ (length_i / feed_i) × 60  (length in mm, feed in mm/min)\n"
        "\n"
        "segments : list of dicts with:\n"
        "  length_mm    : float — segment length (mm)\n"
        "  feed_mm_min  : float — feed rate (mm/min)\n"
        "\n"
        "Returns:\n"
        "  ok            : bool\n"
        "  cycle_time_s  : float — total cycle time (seconds)\n"
        "  cycle_time_min: float — total cycle time (minutes)\n"
        "  n_segments    : int\n"
    ),
    input_schema={
        "type": "object",
        "properties": {
            "segments": {
                "type": "array",
                "description": "Toolpath segments, each with length_mm and feed_mm_min.",
                "items": {
                    "type": "object",
                    "properties": {
                        "length_mm": {"type": "number"},
                        "feed_mm_min": {"type": "number"},
                    },
                    "required": ["length_mm", "feed_mm_min"],
                },
                "minItems": 1,
            },
        },
        "required": ["segments"],
    },
)


async def run_manufacturing_cycle_time(params: dict, ctx: "ProjectCtx") -> str:
    try:
        from kerf_manufacturing.feed_rate import OptimizedSegment, estimate_cycle_time

        raw_segs = params.get("segments")
        if not raw_segs:
            return err_payload("segments is required and must be non-empty", "BAD_ARGS")

        # Accept either OptimizedSegment-shaped dicts or plain {length_mm, feed_mm_min}
        pseudo_segs: list[OptimizedSegment] = []
        for i, s in enumerate(raw_segs):
            pseudo_segs.append(
                OptimizedSegment(
                    segment_id=i,
                    length_mm=float(s.get("length_mm", 0.0)),
                    base_feed_mm_min=float(s.get("feed_mm_min", 0.0)),
                    feed_mm_min=float(s.get("feed_mm_min", 0.0)),
                    cap_reason="nominal",
                    mrr_mm3_per_min=0.0,
                    doc_mm=0.0,
                    woc_mm=0.0,
                )
            )

        t = estimate_cycle_time(pseudo_segs)

        return ok_payload({
            "ok": True,
            "cycle_time_s": round(t, 3),
            "cycle_time_min": round(t / 60.0, 4),
            "n_segments": len(pseudo_segs),
        })

    except Exception as exc:
        return err_payload(str(exc), "MANUFACTURING_CYCLE_TIME_ERROR")


# ---------------------------------------------------------------------------
# TOOLS list consumed by plugin
# ---------------------------------------------------------------------------

from kerf_manufacturing.am_tool import AM_TOOLS  # noqa: E402
from kerf_manufacturing.am_thermo_tool import AM_THERMO_TOOLS  # noqa: E402

TOOLS = [
    ("manufacturing_moldflow", manufacturing_moldflow_spec, run_manufacturing_moldflow),
    ("manufacturing_optimize_feed", manufacturing_optimize_feed_spec, run_manufacturing_optimize_feed),
    ("manufacturing_cycle_time", manufacturing_cycle_time_spec, run_manufacturing_cycle_time),
    *AM_TOOLS,
    *AM_THERMO_TOOLS,
]
