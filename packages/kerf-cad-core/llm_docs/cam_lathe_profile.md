# cam_emit_lathe_gcode

*Module: `kerf_cad_core.cam_lathe_profile` · Domain: cad*

## Description

Emit a complete Fanuc RS-274 lathe G-code program (G71 rough turning + G70 finish turning) from a 2-D axis-symmetric profile.

Profile: list of [Z_mm, X_radius_mm] pairs (Z axial, X radius, not diameter).
stock_x_mm: initial stock radius (must exceed max profile X).

Returns the G-code string plus metadata (RPM, feed, pass count, warnings).

Includes: G71 rough cycle, G70 finish cycle, G96 CSS, G97 constant-RPM, M03/M05 spindle on/off, M06 tool change.

Dialect: Fanuc 0i-TF/30i ONLY. Heidenhain, Siemens, Mazak, Okuma lathe cycles are out of scope.

Refs: NIST RS-274/NGC (Kramer et al. 2000); Smid CNC Programming Handbook (2008) §6.

Errors: {ok:false, reason} — never raises.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "profile": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "description": "2-D turning profile: list of [Z_mm, X_radius_mm] pairs. Z = axial (mm, positive towards tailstock). X = radius in mm (not diameter). Must be \u2265 0. Minimum 2 points; Z must be monotone.",
      "minItems": 2
    },
    "stock_x_mm": {
      "type": "number",
      "description": "Initial stock radius (mm). Must be > max profile X."
    },
    "stock_z_mm": {
      "type": "number",
      "description": "Axial facing-stock overhang (mm). Default 2.0."
    },
    "tool_id": {
      "type": "integer",
      "description": "Tool number (T-code, 1\u201399). Default 1.",
      "minimum": 1,
      "maximum": 99
    },
    "sfm": {
      "type": "number",
      "description": "Surface cutting speed in ft/min. Default 600 (steel, carbide). Smid 2008 \u00a76.1: 400\u2013800 SFM for medium-carbon steel."
    },
    "ipr": {
      "type": "number",
      "description": "Roughing feed per revolution (mm/rev). Default 0.25. Smid 2008 \u00a76.1: 0.15\u20130.50 mm/rev roughing range."
    },
    "finish_ipr": {
      "type": "number",
      "description": "Finishing feed per revolution (mm/rev). Default 0.10."
    },
    "doc_mm": {
      "type": "number",
      "description": "Radial depth of cut per roughing pass (mm). Default 2.0."
    },
    "finish_allow_x_mm": {
      "type": "number",
      "description": "Diametric finish allowance left for G70 (U word on G71, mm). Default 0.5."
    },
    "finish_allow_z_mm": {
      "type": "number",
      "description": "Axial finish allowance (W word on G71, mm). Default 0.1."
    },
    "retract_mm": {
      "type": "number",
      "description": "Rapid clearance for return moves (mm). Default 5.0."
    },
    "program_number": {
      "type": "integer",
      "description": "Fanuc O-number (1\u20139999). Omitted when absent.",
      "minimum": 1,
      "maximum": 9999
    },
    "header_comment": {
      "type": "string",
      "description": "Optional program header comment."
    }
  },
  "required": [
    "profile",
    "stock_x_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="cam_emit_lathe_gcode",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
