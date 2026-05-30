"""
LLM tool: slicing_generate_infill

Generate 2D infill toolpath segments for a 3D-print layer cross-section using
one of four built-in pattern libraries:

  - gyroid     — TPMS gyroid surface (Schoen 1970), density-controlled
  - honeycomb  — regular hexagonal honeycomb grid
  - triangular — three-family triangular grid at 0°/60°/120°
  - concentric — inward offsets of the layer boundary polygon

Schema
------
{
  "pattern": "gyroid" | "honeycomb" | "triangular" | "concentric",
  "layer_polygon": [[x0,y0], [x1,y1], ...],   // closed polygon vertices (mm)
  "params": {
    // gyroid
    "density":       0.20,   // fill fraction [0,1]
    "cell_size":     10.0,   // TPMS period / hex cell / tri spacing in mm
    "z":             0.0,    // layer height in mm
    // honeycomb
    "wall_thickness": 0.4,   // mm
    // triangular
    "line_width":    0.4,    // mm
    // concentric
    "n_offsets":     5,
    "offset_step":   null    // mm; null → auto from polygon inradius
  }
}

Returns
-------
ok_payload({
  "pattern":       "<kind>",
  "segment_count": <int>,
  "segments":      [[x0,y0,x1,y1], ...],  // truncated to 2000
  "total_length_mm": <float>,
  "note":          "<optional warning>"
})
"""
from __future__ import annotations

import json

try:
    from kerf_chat.tools.registry import ToolSpec, err_payload, ok_payload, register
    from kerf_core.utils.context import ProjectCtx
except ImportError:
    from kerf_slicing._compat import ToolSpec, err_payload, ok_payload, register, ProjectCtx  # type: ignore


slicing_generate_infill_spec = ToolSpec(
    name="slicing_generate_infill",
    description=(
        "Generate 2D infill toolpath segments for a 3D-print layer cross-section "
        "using one of four pattern types: gyroid (TPMS), honeycomb, triangular grid, "
        "or concentric. Returns line segments clipped to the layer polygon that can "
        "be used for UI preview or direct G-code path planning. "
        "Does not require CuraEngine."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "pattern": {
                "type": "string",
                "enum": ["gyroid", "honeycomb", "triangular", "concentric"],
                "description": (
                    "Infill pattern type. "
                    "'gyroid': TPMS minimal surface (density-controlled, good isotropic strength). "
                    "'honeycomb': regular hexagonal grid (efficient material use). "
                    "'triangular': three-family 0/60/120° line grid (fast print, uniform strength). "
                    "'concentric': inward offsets of boundary (decorative / flexible prints)."
                ),
            },
            "layer_polygon": {
                "type": "array",
                "items": {
                    "type": "array",
                    "items": {"type": "number"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "minItems": 3,
                "description": (
                    "Ordered list of [x, y] vertices (mm) defining the closed "
                    "layer cross-section polygon. Last vertex is implicitly connected "
                    "to the first."
                ),
            },
            "params": {
                "type": "object",
                "description": (
                    "Pattern-specific parameters. All optional — defaults give good results. "
                    "density: fill fraction [0,1] (gyroid/triangular, default 0.20/0.25). "
                    "cell_size: cell period in mm (default 10 gyroid, 5 honeycomb, 8 triangular). "
                    "z: layer height in mm for gyroid phase (default 0). "
                    "wall_thickness: honeycomb wall mm (default 0.4). "
                    "line_width: triangular extrusion width mm (default 0.4). "
                    "n_offsets: concentric ring count (default 5). "
                    "offset_step: concentric ring spacing mm (default auto)."
                ),
                "properties": {
                    "density":        {"type": "number", "minimum": 0.01, "maximum": 1.0},
                    "cell_size":      {"type": "number", "minimum": 0.5},
                    "z":              {"type": "number"},
                    "wall_thickness": {"type": "number", "minimum": 0.1},
                    "line_width":     {"type": "number", "minimum": 0.1},
                    "n_offsets":      {"type": "integer", "minimum": 1, "maximum": 100},
                    "offset_step":    {"type": ["number", "null"]},
                },
            },
        },
        "required": ["pattern", "layer_polygon"],
    },
)


@register(slicing_generate_infill_spec, write=False)
async def slicing_generate_infill(ctx: "ProjectCtx", args: bytes) -> str:
    try:
        a = json.loads(args)
    except Exception as e:
        return err_payload(f"invalid args: {e}", "BAD_ARGS")

    pattern = a.get("pattern", "")
    layer_polygon = a.get("layer_polygon")
    params = a.get("params") or {}

    if not pattern:
        return err_payload("'pattern' is required", "BAD_ARGS")
    if not layer_polygon or len(layer_polygon) < 3:
        return err_payload(
            "'layer_polygon' must be a list of at least 3 [x,y] pairs", "BAD_ARGS"
        )

    # Validate polygon entries
    try:
        poly_pts = [(float(p[0]), float(p[1])) for p in layer_polygon]
    except (TypeError, IndexError, ValueError) as e:
        return err_payload(f"invalid layer_polygon entry: {e}", "BAD_ARGS")

    # Generate
    try:
        from kerf_slicing.infill_patterns import fill_perimeter_with_pattern
        segments = fill_perimeter_with_pattern(poly_pts, pattern, params)
    except ValueError as e:
        return err_payload(str(e), "BAD_ARGS")
    except Exception as e:
        return err_payload(f"infill generation failed: {e}", "ERROR")

    total_length = sum(s.length() for s in segments)

    # Truncate to 2000 segments to keep payload manageable
    MAX_SEGS = 2000
    note = None
    if len(segments) > MAX_SEGS:
        note = (
            f"Result truncated to {MAX_SEGS} of {len(segments)} segments. "
            "Retrieve the full set via the HTTP route /slicing/infill."
        )
        segments = segments[:MAX_SEGS]

    seg_list = [[s.x0, s.y0, s.x1, s.y1] for s in segments]

    return ok_payload({
        "pattern":         pattern,
        "segment_count":   len(segments),
        "segments":        seg_list,
        "total_length_mm": round(total_length, 3),
        **({"note": note} if note else {}),
    })
