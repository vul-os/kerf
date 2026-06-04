# marine

*Module: `kerf_cad_core.marine.tools` · Domain: cad*

This module registers **4** LLM tool(s):

- [`marine_hull_from_offsets`](#marine-hull-from-offsets)
- [`marine_fairing_report`](#marine-fairing-report)
- [`marine_hydrostatics`](#marine-hydrostatics)
- [`marine_hull_fair_surface`](#marine-hull-fair-surface)

---

## `marine_hull_from_offsets`

Build a parametric NURBS-loft hull recipe from a table of half-breadths (offset table).

Input: a list of {station, waterline, half_breadth} rows (metres).
  station      — longitudinal X position (0=bow, increasing to stern)
  waterline    — vertical Z position (0=keel, increasing upward)
  half_breadth — half-beam at that station/waterline (>= 0)

Output: {ok, op, stations, waterlines, sections, knot_params, loa, max_half_beam, depth, station_count, waterline_count}.

The returned recipe (op='marine_loft_hull') is pure parametric data; a downstream NURBS worker uses it to produce the actual surface.  Pass it to marine_fairing_report or marine_hydrostatics for analysis.

Errors returned as {ok: false, errors: [...]} for malformed tables.  Never raises.

Typical workflow:
  1. marine_hull_from_offsets(offsets=...) → recipe + dimensions
  2. marine_fairing_report(offsets=...)    → quality metrics
  3. marine_hydrostatics(offsets=...)      → Awp, ∇, LCB

### Input schema

```json
{
  "type": "object",
  "properties": {
    "offsets": {
      "type": "array",
      "description": "Table of half-breadth offsets.  Each entry is an object with:\n  station (number)      \u2014 longitudinal position in metres (0 = bow, increasing to stern)\n  waterline (number)    \u2014 vertical position in metres (0 = keel baseline, increasing upward)\n  half_breadth (number) \u2014 half-beam (port or starboard) at that station/waterline in metres (>= 0)\nMinimum 3 rows required; at least 2 distinct stations and 2 distinct waterlines.  Duplicate (station, waterline) pairs are rejected.",
      "items": {
        "type": "object",
        "properties": {
          "station": {
            "type": "number"
          },
          "waterline": {
            "type": "number"
          },
          "half_breadth": {
            "type": "number"
          }
        },
        "required": [
          "station",
          "waterline",
          "half_breadth"
        ]
      }
    }
  },
  "required": [
    "offsets"
  ]
}
```

---

## `marine_fairing_report`

Compute hull fairing quality metrics for a half-breadth offset table.

Three metrics are reported:

1. curvature_monotonicity (per station)
   Checks that the half-breadth profile at each station is convex: non-decreasing from keel to max-breadth waterline, non-increasing above it.  A 'kink' is flagged when the sign of consecutive differences changes more than once (inflection point not attributable to beam turnover).

2. batten_energy (per station)
   Approximate bending energy (m³) of a natural cubic spline fit to the WL→Y profile at each station.  Lower energy = fairer curve.  Analogous to a physical batten resisting bending.

3. roughness_per_waterline (longitudinal)
   RMS of second finite differences of half-breadths along each waterline.  Measures fairness in the longitudinal (station) direction.  0.0 on a perfectly fair hull.

overall_roughness: mean of all per-waterline RMS values.

Errors returned as {ok: false, errors: [...]}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "offsets": {
      "type": "array",
      "description": "Table of half-breadth offsets.  Each entry is an object with:\n  station (number)      \u2014 longitudinal position in metres (0 = bow, increasing to stern)\n  waterline (number)    \u2014 vertical position in metres (0 = keel baseline, increasing upward)\n  half_breadth (number) \u2014 half-beam (port or starboard) at that station/waterline in metres (>= 0)\nMinimum 3 rows required; at least 2 distinct stations and 2 distinct waterlines.  Duplicate (station, waterline) pairs are rejected.",
      "items": {
        "type": "object",
        "properties": {
          "station": {
            "type": "number"
          },
          "waterline": {
            "type": "number"
          },
          "half_breadth": {
            "type": "number"
          }
        },
        "required": [
          "station",
          "waterline",
          "half_breadth"
        ]
      }
    }
  },
  "required": [
    "offsets"
  ]
}
```

---

## `marine_hydrostatics`

Compute basic hydrostatic properties from a hull half-breadth offset table.

Method: composite Simpson's 1/3 rule — exact for polynomials up to degree 3.  Reference: D. J. Eyres, Ship Stability for Masters and Mates, Chapter 6.

Quantities
----------
waterplane_area_m2
    Awp = ∫₀^L 2·y(x,T) dx  [m²]
    Area of the waterplane at the design waterline T.

displaced_volume_m3
    ∇ = ∫₀^L Aₓ(x) dx  [m³]
    Displaced volume below the design waterline.
    For a rectangular box barge (length L, beam B, draft T):
        ∇ = L × B × T  (verified by Simpson's rule for constant offsets)

lcb_from_bow_m
    LCB = (1/∇) · ∫₀^L x·Aₓ(x) dx  [m from bow]
    Longitudinal Centre of Buoyancy measured from the first station.

Parameters
----------
offsets          — half-breadth offset table
design_waterline — optional float (metres); defaults to max WL in table

Errors returned as {ok: false, errors: [...]}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "offsets": {
      "type": "array",
      "description": "Table of half-breadth offsets.  Each entry is an object with:\n  station (number)      \u2014 longitudinal position in metres (0 = bow, increasing to stern)\n  waterline (number)    \u2014 vertical position in metres (0 = keel baseline, increasing upward)\n  half_breadth (number) \u2014 half-beam (port or starboard) at that station/waterline in metres (>= 0)\nMinimum 3 rows required; at least 2 distinct stations and 2 distinct waterlines.  Duplicate (station, waterline) pairs are rejected.",
      "items": {
        "type": "object",
        "properties": {
          "station": {
            "type": "number"
          },
          "waterline": {
            "type": "number"
          },
          "half_breadth": {
            "type": "number"
          }
        },
        "required": [
          "station",
          "waterline",
          "half_breadth"
        ]
      }
    },
    "design_waterline": {
      "type": "number",
      "description": "Design waterline (draft) in metres.  Optional; defaults to the maximum waterline in the offset table."
    }
  },
  "required": [
    "offsets"
  ]
}
```

---

## `marine_hull_fair_surface`

Build a faired NURBS hull surface from a table of half-breadths and attach curvature-comb analysis.

Fairing workflow:
  1. Fit a natural cubic spline (minimum bending energy) through each
     station's waterline → half-breadth profile and re-evaluate it at
     the original waterline positions (transverse fairing).
  2. Repeat across stations at each waterline (longitudinal fairing).
  3. Repeat for `fairing_passes` iterations (default 1; 2 passes for
     high-curvature hulls).
  4. Build a degree-3 × degree-3 NURBS surface from the faired grid.
  5. Sample principal curvatures (k1/k2, mean H, Gaussian K) on a UV
     grid via GeomLProp_SLProps-equivalent Python code, producing a
     `curvature_combs` payload consumed by `CurvatureCombOverlay.jsx`.

Returns:
  nurbs_surface    — degree/knot/control-point data for the faired surface
  curvature_combs  — sampled k1/k2/H/K + sample points for the viewport
  fairness_metrics — monotonicity, batten energy improvement, roughness

Use marine_fairing_report to inspect the raw (unfaired) offsets first.
Errors returned as {ok: false, errors: [...]}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "offsets": {
      "type": "array",
      "description": "Table of half-breadth offsets.  Each entry is an object with:\n  station (number)      \u2014 longitudinal position in metres (0 = bow, increasing to stern)\n  waterline (number)    \u2014 vertical position in metres (0 = keel baseline, increasing upward)\n  half_breadth (number) \u2014 half-beam (port or starboard) at that station/waterline in metres (>= 0)\nMinimum 3 rows required; at least 2 distinct stations and 2 distinct waterlines.  Duplicate (station, waterline) pairs are rejected.",
      "items": {
        "type": "object",
        "properties": {
          "station": {
            "type": "number"
          },
          "waterline": {
            "type": "number"
          },
          "half_breadth": {
            "type": "number"
          }
        },
        "required": [
          "station",
          "waterline",
          "half_breadth"
        ]
      }
    },
    "uv_density": {
      "type": "number",
      "description": "UV grid step for curvature-comb sampling as a fraction of the parameter range (default 0.1 \u2192 ~10\u00d710 grid). Range: 0.01\u20130.5."
    },
    "scale_factor": {
      "type": "number",
      "description": "Comb line length multiplier (default 10). Increase for nearly-flat surfaces; decrease for high-curvature ones."
    },
    "fairing_passes": {
      "type": "integer",
      "description": "Number of transverse + longitudinal fairing iterations (default 1). Use 2\u20133 for irregular or high-curvature hulls."
    }
  },
  "required": [
    "offsets"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
