# cam_optimize_feedrate_lookahead

*Module: `kerf_cad_core.cam_feedrate_lookahead` · Domain: cad*

## Description

Compute the optimal feedrate at each waypoint of a CAM toolpath using the two-pass corner lookahead algorithm (Erkorkmaz-Altintas 2001 / Altintas 2012 §5.7).

The algorithm:
  1. Computes the maximum corner feedrate at each interior waypoint:
       V_corner = sqrt(a_max × r_blend / sin(θ/2))  where θ is the turning angle.
  2. Forward pass: accelerate from rest, capped by V_target and V_corner.
  3. Backward pass: decelerate toward each corner, intersected with forward pass.

The result is a per-waypoint feedrate schedule (mm/s), corner angles (radians), and an estimated cycle time.

Profile types:
  'trapezoid' (default) — constant-acceleration (trapezoidal) velocity profile.
  's-curve' — jerk-limited 7-segment S-curve profile per Lambrechts-Boerlage-
    Steinbuch (2005) / Erkorkmaz-Altintas §3.3. Cycle time accounts for jerk limiting (typically 10–30% longer than trapezoidal at same A_max).

Inputs:
  waypoints        — list of {x, y, z} positions (mm)
  max_feedrate     — maximum feedrate (mm/s)
  max_accel        — maximum tangential acceleration (mm/s²)
  blending_radius  — corner blending arc radius in mm (default 0.1)
  profile_type     — 'trapezoid' or 's-curve' (default 'trapezoid')

## Input schema

```json
{
  "type": "object",
  "required": [
    "waypoints",
    "max_feedrate",
    "max_accel"
  ],
  "properties": {
    "waypoints": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "x": {
            "type": "number"
          },
          "y": {
            "type": "number"
          },
          "z": {
            "type": "number"
          }
        },
        "required": [
          "x",
          "y",
          "z"
        ]
      },
      "description": "Ordered list of (X, Y, Z) waypoints in mm.",
      "minItems": 1
    },
    "max_feedrate": {
      "type": "number",
      "description": "Maximum feedrate (mm/s). Typical range 100\u20135000 mm/s."
    },
    "max_accel": {
      "type": "number",
      "description": "Maximum tangential acceleration (mm/s\u00b2). Typical range 500\u201310000 mm/s\u00b2."
    },
    "blending_radius": {
      "type": "number",
      "description": "Corner blending arc radius (mm). Default 0.1 mm.",
      "default": 0.1
    },
    "profile_type": {
      "type": "string",
      "enum": [
        "trapezoid",
        "s-curve"
      ],
      "description": "Velocity profile: 'trapezoid' (default) or 's-curve' (jerk-limited).",
      "default": "trapezoid"
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="cam_optimize_feedrate_lookahead",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
