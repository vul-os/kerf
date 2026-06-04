# nurbs_solid_boolean

*Module: `kerf_cad_core.geom.nurbs_boolean` · Domain: cad*

## Description

Compute a general solid boolean (union / intersect / subtract) between two closed solid bodies whose faces may be arbitrary NURBS surfaces.

This implements the foundational general-case boolean for NURBS-faced bodies (GK-P foundational kernel).  Inputs are described as bounding boxes (lo/hi corners) that are used to build minimal box bodies for the operation — pass actual Body objects from the CAD scene in server context.

op: 'union' | 'intersect' | 'subtract'

Returns: {ok, op, body_a_faces, body_b_faces, result_faces, valid, method}
Errors: {ok:false, reason}.  Never raises.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "lo_a": {
      "type": "array",
      "description": "Body A min corner [x, y, z]",
      "items": {
        "type": "number"
      }
    },
    "hi_a": {
      "type": "array",
      "description": "Body A max corner [x, y, z]",
      "items": {
        "type": "number"
      }
    },
    "lo_b": {
      "type": "array",
      "description": "Body B min corner [x, y, z]",
      "items": {
        "type": "number"
      }
    },
    "hi_b": {
      "type": "array",
      "description": "Body B max corner [x, y, z]",
      "items": {
        "type": "number"
      }
    },
    "op": {
      "type": "string",
      "description": "Boolean operation",
      "enum": [
        "union",
        "intersect",
        "subtract"
      ]
    },
    "tol": {
      "type": "number",
      "description": "Tolerance (default 1e-6)"
    }
  },
  "required": [
    "lo_a",
    "hi_a",
    "lo_b",
    "hi_b",
    "op"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="nurbs_solid_boolean",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
