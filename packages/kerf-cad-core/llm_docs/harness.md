# harness

*Module: `kerf_cad_core.harness.tools` · Domain: cad*

This module registers **3** LLM tool(s):

- [`harness_route`](#harness-route)
- [`harness_bundle_diameter`](#harness-bundle-diameter)
- [`harness_bom`](#harness-bom)

---

## `harness_route`

Route a wiring harness in 3D through connector endpoints and optional guide (via) points, producing a smoothed polyline bundle path.

Inputs:
  endpoints   — list of exactly 2 (or more for trunk) {x,y,z} points
  guides      — optional list of via-points the harness passes near
  wire_specs  — optional [{gauge, count}, ...] wire specifications
                gauge is mm² cross-section string e.g. '1.0', '2.5'
  obstacles   — optional list of {min_x,min_y,min_z,max_x,max_y,max_z}
                obstacle bounding boxes (metres)
  branches    — optional list of T-split branches:
                [{branch_id, start, end, guides, wire_specs}, ...]

Smoothing: centripetal Catmull-Rom spline (alpha=0.5) through control points.

Output: {ok, reason, total_length_m, bundle_od_mm, obstacles_hit, branch_count, branches: [{branch_id, total_length_m, bend_ok, segments: [{name, length_m, bundle_od_mm, min_bend_radius_m, bend_ok, wire_count, control_points, smoothed_point_count}]}]}.

ok=false when bend-radius check fails (min bend radius < 10× bundle OD) or path intersects an obstacle — the violation is reported in 'reason', never raised as an exception.

Units: metres.  All coordinates in metres.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "endpoints": {
      "type": "array",
      "description": "Connector endpoints as [{x,y,z}, ...] (metres). Minimum 2 points: [start, end].",
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
      "minItems": 2
    },
    "guides": {
      "type": "array",
      "description": "Optional via-points for trunk routing ({x,y,z} metres). The harness is smoothed through these points.",
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
      }
    },
    "wire_specs": {
      "type": "array",
      "description": "Wire specifications [{gauge, count}]. gauge: mm\u00b2 cross-section area string e.g. '0.5', '1.0', '2.5'. count: number of wires of that gauge.",
      "items": {
        "type": "object",
        "properties": {
          "gauge": {
            "type": "string"
          },
          "count": {
            "type": "integer",
            "minimum": 1
          }
        },
        "required": [
          "gauge",
          "count"
        ]
      }
    },
    "obstacles": {
      "type": "array",
      "description": "Axis-aligned obstacle bounding boxes {min_x, min_y, min_z, max_x, max_y, max_z} (metres). Path flagged if any point lies inside a bbox.",
      "items": {
        "type": "object",
        "properties": {
          "min_x": {
            "type": "number"
          },
          "min_y": {
            "type": "number"
          },
          "min_z": {
            "type": "number"
          },
          "max_x": {
            "type": "number"
          },
          "max_y": {
            "type": "number"
          },
          "max_z": {
            "type": "number"
          }
        },
        "required": [
          "min_x",
          "min_y",
          "min_z",
          "max_x",
          "max_y",
          "max_z"
        ]
      }
    },
    "branches": {
      "type": "array",
      "description": "T-split branch definitions. Each branch: {branch_id, start?, end (required), guides?, wire_specs?}. If start is omitted, branch starts from endpoints[1] (trunk end).",
      "items": {
        "type": "object",
        "properties": {
          "branch_id": {
            "type": "string"
          },
          "start": {
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
            }
          },
          "end": {
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
          "guides": {
            "type": "array"
          },
          "wire_specs": {
            "type": "array"
          }
        },
        "required": [
          "end"
        ]
      }
    }
  },
  "required": [
    "endpoints"
  ]
}
```

---

## `harness_bundle_diameter`

Compute the outer diameter of a wiring harness bundle from wire count and gauge specifications.

Method: sum all insulated wire cross-section areas, divide by bundle fill factor (0.78, hexagonal close-packing approximation), compute equivalent circular bundle diameter.

Input: [{gauge, count}, ...] wire specifications.
  gauge: mm² cross-section area string e.g. '0.5', '1.0', '2.5'
  count: number of wires of that gauge

Output: {ok, bundle_od_mm, bundle_od_m, wire_count_total, wire_specs_parsed}.

Errors returned as {ok: false, reason: ...}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "wire_specs": {
      "type": "array",
      "description": "Wire specifications [{gauge, count}]. gauge: mm\u00b2 cross-section area string. count: number of wires of that gauge.",
      "items": {
        "type": "object",
        "properties": {
          "gauge": {
            "type": "string"
          },
          "count": {
            "type": "integer",
            "minimum": 1
          }
        },
        "required": [
          "gauge",
          "count"
        ]
      },
      "minItems": 1
    }
  },
  "required": [
    "wire_specs"
  ]
}
```

---

## `harness_bom`

Generate a wire/length/segment rollup Bill of Materials (BOM) from a routed harness result.

Input: a harness result dict from harness_route (the full JSON output).

For each segment in each branch, the BOM lists:
  gauge         — wire gauge (mm² cross-section)
  count         — number of wires of that gauge in the segment
  segment_name  — segment identifier
  branch_id     — branch identifier
  length_m      — routed length of the segment
  total_wire_length_m — count × length_m (material to procure)

Output: {ok, entries: [...], totals_by_gauge: {gauge: total_m}, grand_total_wire_length_m}.

totals_by_gauge sums total_wire_length_m across all segments for each gauge — use this for procurement quantities.

Errors returned as {ok: false, reason: ...}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "harness": {
      "type": "object",
      "description": "Harness result dict from harness_route. Must contain 'branches' list with segments."
    },
    "wire_specs": {
      "type": "array",
      "description": "Optional wire_specs to assign to segments that have none. If the harness was routed without wire_specs, provide them here.",
      "items": {
        "type": "object",
        "properties": {
          "gauge": {
            "type": "string"
          },
          "count": {
            "type": "integer",
            "minimum": 1
          }
        },
        "required": [
          "gauge",
          "count"
        ]
      }
    }
  },
  "required": [
    "harness"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
