# route_with_shove

*Module: `kerf_electronics.tools.shove_router` · Domain: electronics*

## Description

KiCad-style push-pull (shove) router for PCB. When routing a new trace that would overlap an existing same-layer trace, the existing trace is pushed perpendicular by clearance while preserving its net and endpoints.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "object",
      "description": "CircuitJSON board"
    },
    "layer": {
      "type": "string",
      "description": "Layer name (e.g. 'top', 'bottom')"
    },
    "points": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "description": "New trace points as [[x,y], ...]"
    },
    "clearance_mm": {
      "type": "number",
      "default": 0.25,
      "description": "Clearance distance in mm"
    }
  },
  "required": [
    "circuit_json",
    "layer",
    "points"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="route_with_shove",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
