# nurbs_trim_loop_heal

*Module: `kerf_cad_core.geom.trim_loop_heal` · Domain: cad*

## Description

Repair T-junctions, dead loops, and orientation errors in the 2-D UV-domain trim loops of a NURBS face.  Operates purely in parametric (UV) space — does not touch 3-D B-rep topology.

Pass one outer loop and zero or more inner (hole) loops as UV polygon lists.  The healer performs four steps in order:
  1. T-junction merge — vertices within `tol` snapped to a single      cluster representative (Sederberg-Zheng-Bakenov-Nasri 2003).
  2. Dead-loop removal — loops with < 3 distinct vertices or |area|      < tol² are discarded.
  3. Orientation fix — outer loop forced CCW; inner loops forced CW      (Eberly 2008 shoelace sign test).
  4. Self-intersection detection — interior crossings are counted and      reported; the loop is returned unchanged (no auto-fix).

Returns:
  ok                  : bool
  outer               : list of [u, v] — healed outer loop
  inners              : list[list[u,v]] — healed inner loops
  tjunctions_merged   : int
  deadloops_removed   : int
  orientations_fixed  : int
  self_intersections  : int — non-zero means the loop is invalid;
                        the original outer is returned unchanged

Errors: {ok: false, reason} for invalid inputs.  Never raises.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "outer": {
      "type": "array",
      "description": "Outer boundary loop as a list of [u, v] UV pairs.  Should be CCW; will be auto-corrected if CW.  Do NOT repeat the first vertex at the end.",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      }
    },
    "inners": {
      "type": "array",
      "description": "Zero or more inner (hole) loops, each a list of [u, v] pairs.  Should be CW; will be auto-corrected if CCW.",
      "items": {
        "type": "array",
        "items": {
          "type": "array",
          "items": {
            "type": "number"
          },
          "minItems": 2,
          "maxItems": 2
        }
      }
    },
    "tol": {
      "type": "number",
      "description": "UV-space merge / area tolerance (default 1e-6)."
    },
    "face_id": {
      "type": "string",
      "description": "Optional identifier for this face (informational only)."
    }
  },
  "required": [
    "outer"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="nurbs_trim_loop_heal",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
