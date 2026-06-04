# cam_emit_gcode

*Module: `kerf_cad_core.cam_gcode_emit` · Domain: cad*

## Description

Emit Fanuc-compatible RS-274 G-code from a CAM toolpath (list of waypoints).

Supported waypoint types:
  rapid        — G00 rapid positioning
  linear       — G01 linear interpolation at feedrate F
  arc_cw       — G02 clockwise arc (I/J centre offsets from arc start)
  arc_ccw      — G03 counter-clockwise arc (I/J centre offsets from arc start)
  spindle_on   — M03 spindle on CW (field: s = RPM)
  spindle_off  — M05 spindle stop
  tool_change  — M05 + T.. M06 tool change (field: tool = number)
  comment      — inline comment in parentheses (field: comment = text)

Each motion waypoint has: x, y, z (mm), optional f (feedrate mm/min), optional s (spindle RPM).  Arc waypoints additionally require i, j (X/Y offsets from arc start to arc centre).

Returns: {gcode, line_count, warnings[]}.

Dialect: Fanuc 0i/18i/21i/30i + Haas (Fanuc-compatible) + GRBL ≥ 1.1.
Out of scope: LinuxCNC %, Heidenhain TCPM, Siemens TRAORI, Mazak Smooth.

References:
  NIST RS-274/NGC Interpreter Version 3 (Kramer et al. 2000) §3.4–3.8.
  Smid, P. CNC Programming Handbook (2008) §3.

## Input schema

```json
{
  "type": "object",
  "required": [
    "toolpath"
  ],
  "properties": {
    "toolpath": {
      "type": "array",
      "description": "Ordered list of waypoint dicts.",
      "items": {
        "type": "object",
        "properties": {
          "type": {
            "type": "string",
            "enum": [
              "rapid",
              "linear",
              "arc_cw",
              "arc_ccw",
              "spindle_on",
              "spindle_off",
              "tool_change",
              "comment"
            ]
          },
          "x": {
            "type": "number",
            "description": "X coordinate (mm)"
          },
          "y": {
            "type": "number",
            "description": "Y coordinate (mm)"
          },
          "z": {
            "type": "number",
            "description": "Z coordinate (mm)"
          },
          "f": {
            "type": "number",
            "description": "Feedrate (mm/min)"
          },
          "s": {
            "type": "number",
            "description": "Spindle RPM"
          },
          "i": {
            "type": "number",
            "description": "Arc centre X offset from start (mm)"
          },
          "j": {
            "type": "number",
            "description": "Arc centre Y offset from start (mm)"
          },
          "tool": {
            "type": "integer",
            "description": "Tool number for tool_change"
          },
          "comment": {
            "type": "string",
            "description": "Comment text"
          }
        },
        "required": [
          "type"
        ]
      },
      "minItems": 1
    },
    "header_comment": {
      "type": "string",
      "description": "Optional program header comment (no parentheses needed)."
    },
    "program_number": {
      "type": "integer",
      "description": "Fanuc O-number 1\u20139999 (optional; omitted when not set).",
      "minimum": 1,
      "maximum": 9999
    },
    "coord_decimals": {
      "type": "integer",
      "description": "Decimal places for X/Y/Z/I/J words (default 4).",
      "default": 4,
      "minimum": 1,
      "maximum": 6
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="cam_emit_gcode",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
