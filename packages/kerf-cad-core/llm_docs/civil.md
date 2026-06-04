# civil

*Module: `kerf_cad_core.civil.tools` · Domain: cad*

This module registers **4** LLM tool(s):

- [`civil_terrain`](#civil-terrain)
- [`civil_pad`](#civil-pad)
- [`civil_earthwork`](#civil-earthwork)
- [`civil_grading_report`](#civil-grading-report)

---

## `civil_terrain`

Build a Triangulated Irregular Network (TIN) from survey points and return surface statistics.

Input: a list of {x, y, z} objects (metres) — at least 3 non-collinear points.

Output: {ok, point_count, triangle_count, area_m2, min_elevation_m, max_elevation_m, elevation_range_m}.

Errors returned as {ok: false, errors: [...]} for < 3 points or collinear inputs.  Never raises.

Triangulation: fan method (hub = lexicographically first point; remaining points sorted by polar angle).  Deterministic and consistent for any input order.

Use this tool first before civil_earthwork.  The tin_points list is passed verbatim to civil_earthwork.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "points": {
      "type": "array",
      "description": "Survey points as {x, y, z} objects (metres). Minimum 3 non-collinear points required.",
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
    }
  },
  "required": [
    "points"
  ]
}
```

---

## `civil_pad`

Define a flat or sloped design platform (pad) for earthwork planning.

A pad is a proposed graded surface defined by:
  - A polygon boundary (list of [x, y] pairs, ≥ 3 vertices)
  - A pad elevation at the polygon centroid (metres)
  - An optional side-slope ratio (1V:nH — horizontal run per 1 m     vertical; e.g. 2.0 means the pad slopes 1 m vertically per 2 m     horizontally from the edge)
  - Optional tilt (dz_dx, dz_dy) to define a sloped pad instead of flat

Output: {ok, pad_elevation, polygon_vertex_count, side_slope_ratio, sloped, dz_dx, dz_dy, design_surface_json}.

The design_surface_json field can be passed directly to civil_earthwork as the design_surface parameter.

Errors returned as {ok: false, errors: [...]} for invalid inputs.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "polygon": {
      "type": "array",
      "description": "Pad boundary as a list of [x, y] pairs (metres). At least 3 vertices required. Example: [[0,0],[10,0],[10,10],[0,10]]",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2
      }
    },
    "pad_elevation": {
      "type": "number",
      "description": "Target elevation of the flat pad surface (metres)."
    },
    "side_slope_ratio": {
      "type": "number",
      "description": "Horizontal run per 1 m of vertical rise (1V:nH). E.g. 2.0 for a 2H:1V slope. Set to 0 (default) for no side slopes (pad edges are vertical)."
    },
    "sloped": {
      "type": "boolean",
      "description": "If true, the pad surface is a tilted plane; pad_elevation applies at the polygon centroid and dz_dx / dz_dy define the tilt. Default false."
    },
    "dz_dx": {
      "type": "number",
      "description": "Elevation gradient in X direction (m/m). Used when sloped=true."
    },
    "dz_dy": {
      "type": "number",
      "description": "Elevation gradient in Y direction (m/m). Used when sloped=true."
    }
  },
  "required": [
    "polygon",
    "pad_elevation"
  ]
}
```

---

## `civil_earthwork`

Compute cut/fill earthwork volumes between an existing ground surface (TIN) and a proposed design surface (pad).

Method: grid sampling at a configurable spacing (default 1 m). At each sample node the existing elevation is interpolated from the TIN and compared with the design surface elevation:
  Δz > 0 → fill (add material)
  Δz < 0 → cut  (remove material)
Volume = |Δz| × cell_area (m³).

Output: {ok, cut_m3, fill_m3, net_m3, balance_ratio, sample_count, grid_spacing_m, cell_area_m2, note}.

balance_ratio = cut / fill. Value ≈ 1.0 → balanced earthwork. > 1 → surplus cut; < 1 → import fill required.

Errors returned as {ok: false, errors: [...]}. Never raises.

Typical workflow:
  1. civil_terrain(points=...) → collect survey points
  2. civil_pad(polygon=..., pad_elevation=...) → design_surface_json
  3. civil_earthwork(tin_points=..., design_surface=design_surface_json)

### Input schema

```json
{
  "type": "object",
  "properties": {
    "tin_points": {
      "type": "array",
      "description": "Existing ground survey points as {x, y, z} objects (metres). Same list passed to civil_terrain.",
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
    "design_surface": {
      "type": "object",
      "description": "Design surface specification from civil_pad output (design_surface_json field). Fields: pad_elevation, polygon, side_slope_ratio, sloped, dz_dx, dz_dy."
    },
    "grid_spacing_m": {
      "type": "number",
      "description": "Sample grid spacing in metres (default 1.0). Smaller values give more accurate volumes at higher cost. Typical range: 0.5\u20135.0 m."
    }
  },
  "required": [
    "tin_points",
    "design_surface"
  ]
}
```

---

## `civil_grading_report`

Format a human-readable grading & earthwork balance report from civil_earthwork output.

Input: the output dict from civil_earthwork (ok, cut_m3, fill_m3, net_m3, balance_ratio, etc.).

Output: {ok, report_text, summary_lines} where report_text is a formatted multi-line string suitable for display or saving, and summary_lines is the same content as a list of strings.

Also accepts optional project_name and site_description strings for the report header.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "earthwork": {
      "type": "object",
      "description": "Earthwork result dict from civil_earthwork. Required fields: cut_m3, fill_m3, net_m3, balance_ratio, sample_count, grid_spacing_m."
    },
    "project_name": {
      "type": "string",
      "description": "Optional project name for the report header."
    },
    "site_description": {
      "type": "string",
      "description": "Optional site description or notes."
    }
  },
  "required": [
    "earthwork"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
