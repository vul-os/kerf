# cam_emit_wire_edm_gcode

*Module: `kerf_cad_core.cam_wire_edm_path` · Domain: cad*

## Description

Emit a complete Fanuc wire-EDM G-code program for a 2-D profile.

Wire EDM uses a charged wire (0.10-0.30 mm) to spark-erode a kerf in conductive metal.  The program includes G41/G42 cutter compensation (D-register = wire_radius + spark_gap), M50/M51 wire feed on/off, G01 linear and G02/G03 circular interpolation, and a straight lead-in to activate compensation safely.

Profile segments: list of [type, ...] where type is:
  ["line", x, y]              — linear cut to (x, y)
  ["arc_cw",  x, y, cx, cy]   — CW arc to (x,y), centre (cx,cy)
  ["arc_ccw", x, y, cx, cy]   — CCW arc to (x,y), centre (cx,cy)
All coordinates in mm.

Compensation radius (D register) = wire_radius + spark_gap; this value must be set in the controller's D01 offset register before running.

HONEST LIMITS: 2-axis (XY) path only.  Wire taper (4-axis U/V axis), threading hole automation, skim passes, and variable-feed corner strategies are NOT modelled.

Dialect: Fanuc wire-EDM (B-59064EN/01): G40/G41/G42, M50/M51, G92.

Refs: Tlusty (2000) §13 (EDM); Fanuc B-59064EN/01; Rajurkar et al. CIRP Annals 62(2):779-801.

Errors: {ok: false, reason} — never raises.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "profile_2d": {
      "type": "array",
      "description": "Profile segments. Each segment is a list:\n  [\"line\", x, y]\n  [\"arc_cw\",  x, y, cx, cy]\n  [\"arc_ccw\", x, y, cx, cy]\nMinimum 1 segment. Coordinates in mm.",
      "items": {
        "type": "array",
        "minItems": 3
      },
      "minItems": 1
    },
    "start_xy": {
      "type": "array",
      "description": "Starting [x, y] position of the profile (mm).",
      "items": {
        "type": "number"
      },
      "minItems": 2,
      "maxItems": 2
    },
    "wire_diameter_mm": {
      "type": "number",
      "description": "Wire diameter (mm). Default 0.25 mm."
    },
    "spark_gap_mm": {
      "type": "number",
      "description": "One-sided spark gap (mm). Default 0.025 mm. Rajurkar 2013: typical 0.010-0.050 mm."
    },
    "side": {
      "type": "string",
      "enum": [
        "left",
        "right"
      ],
      "description": "Compensation side: 'left' -> G41 (workpiece to the left); 'right' -> G42. Default 'left'."
    },
    "feedrate_mm_min": {
      "type": "number",
      "description": "Wire traverse feedrate (mm/min). Default 1.5 mm/min. Tlusty 2000 \u00a713.3: typical 0.3-3.0 mm/min."
    },
    "lead_in_mm": {
      "type": "number",
      "description": "Lead-in straight length (mm). Default 2.0 mm."
    },
    "program_number": {
      "type": "integer",
      "description": "Fanuc O-number (1-9999). Omitted if absent.",
      "minimum": 1,
      "maximum": 9999
    },
    "header_comment": {
      "type": "string",
      "description": "Optional program header comment."
    }
  },
  "required": [
    "profile_2d",
    "start_xy"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="cam_emit_wire_edm_gcode",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
