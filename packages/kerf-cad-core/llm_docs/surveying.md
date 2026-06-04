# surveying

*Module: `kerf_cad_core.surveying.tools` · Domain: cad*

This module registers **12** LLM tool(s):

- [`surveying_dms_to_dd`](#surveying-dms-to-dd)
- [`surveying_dd_to_dms`](#surveying-dd-to-dms)
- [`surveying_bearing_azimuth`](#surveying-bearing-azimuth)
- [`surveying_forward`](#surveying-forward)
- [`surveying_inverse`](#surveying-inverse)
- [`surveying_traverse`](#surveying-traverse)
- [`surveying_traverse_adjust`](#surveying-traverse-adjust)
- [`surveying_area_coordinates`](#surveying-area-coordinates)
- [`surveying_area_dmd`](#surveying-area-dmd)
- [`surveying_poi`](#surveying-poi)
- [`surveying_resection`](#surveying-resection)
- [`surveying_level_loop`](#surveying-level-loop)

---

## `surveying_dms_to_dd`

Convert a degrees-minutes-seconds angle to decimal degrees.

Useful for entering survey angles in DMS notation and converting
to the decimal form required by other surveying tools.

Errors: {ok:false, reason} for out-of-range minutes/seconds. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "degrees": {
      "type": "number",
      "description": "Degrees component (may be negative for south/west)."
    },
    "minutes": {
      "type": "number",
      "description": "Minutes component. Must be in [0, 60)."
    },
    "seconds": {
      "type": "number",
      "description": "Seconds component. Must be in [0, 60)."
    }
  },
  "required": [
    "degrees",
    "minutes",
    "seconds"
  ]
}
```

---

## `surveying_dd_to_dms`

Convert a decimal-degrees angle to degrees-minutes-seconds.

Errors: {ok:false, reason} for non-finite input. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "dd": {
      "type": "number",
      "description": "Angle in decimal degrees."
    }
  },
  "required": [
    "dd"
  ]
}
```

---

## `surveying_bearing_azimuth`

Convert between reduced bearing and whole-circle azimuth.

Mode 'to_azimuth': supply quadrant ('NE'/'SE'/'SW'/'NW') and
bearing_dd (0, 90] → returns azimuth_dd in [0, 360).

Mode 'to_bearing': supply azimuth_dd → returns quadrant and
bearing_dd plus a formatted string like 'N45°30\'00"E'.

Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "mode": {
      "type": "string",
      "enum": [
        "to_azimuth",
        "to_bearing"
      ],
      "description": "Conversion direction."
    },
    "quadrant": {
      "type": "string",
      "enum": [
        "NE",
        "SE",
        "SW",
        "NW"
      ],
      "description": "Required when mode='to_azimuth'."
    },
    "bearing_dd": {
      "type": "number",
      "description": "Bearing in (0, 90]. Required when mode='to_azimuth'."
    },
    "azimuth_dd": {
      "type": "number",
      "description": "Whole-circle azimuth [0, 360). Required when mode='to_bearing'."
    }
  },
  "required": [
    "mode"
  ]
}
```

---

## `surveying_forward`

Compute the coordinates of a new point given a starting point,
whole-circle azimuth, and horizontal distance (polar → rectangular).

Returns northing, easting, delta_N, delta_E.

Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "northing": {
      "type": "number",
      "description": "Starting point northing (m)."
    },
    "easting": {
      "type": "number",
      "description": "Starting point easting (m)."
    },
    "azimuth_dd": {
      "type": "number",
      "description": "Whole-circle azimuth in decimal degrees."
    },
    "distance": {
      "type": "number",
      "description": "Horizontal distance (m). Must be >= 0."
    }
  },
  "required": [
    "northing",
    "easting",
    "azimuth_dd",
    "distance"
  ]
}
```

---

## `surveying_inverse`

Compute the azimuth and horizontal distance between two points
(rectangular → polar conversion).

Returns azimuth_dd, distance, delta_N, delta_E, quadrant, bearing_str.

Errors: {ok:false, reason} if points are coincident. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "n1": {
      "type": "number",
      "description": "From-point northing (m)."
    },
    "e1": {
      "type": "number",
      "description": "From-point easting (m)."
    },
    "n2": {
      "type": "number",
      "description": "To-point northing (m)."
    },
    "e2": {
      "type": "number",
      "description": "To-point easting (m)."
    }
  },
  "required": [
    "n1",
    "e1",
    "n2",
    "e2"
  ]
}
```

---

## `surveying_traverse`

Compute the linear misclosure and precision ratio for a closed
traverse.

Each leg requires 'azimuth_dd' (decimal degrees) and 'distance' (m).
A UserWarning is issued (not raised) if precision is worse than
the tolerance ratio.

Returns closure_N, closure_E, linear_misclosure, traverse_length,
precision_ratio, precision_ok, and per-leg delta_N / delta_E.

Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "legs": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "azimuth_dd": {
            "type": "number"
          },
          "distance": {
            "type": "number"
          }
        },
        "required": [
          "azimuth_dd",
          "distance"
        ]
      },
      "description": "List of traverse legs."
    },
    "tolerance": {
      "type": "number",
      "description": "Acceptable precision ratio (default 1/5000 = 0.0002). A warning is issued if exceeded."
    }
  },
  "required": [
    "legs"
  ]
}
```

---

## `surveying_traverse_adjust`

Adjust a closed traverse using the Compass (Bowditch) or Transit rule.

Each leg requires 'azimuth_dd' and 'distance'.

method='compass' (default): corrections proportional to leg distance.
method='transit':           corrections proportional to |latitude|/|departure|.

Returns adjusted_legs (with corrected delta_N/delta_E), cumulative
station coordinates, and closure before/after adjustment.

Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "legs": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "azimuth_dd": {
            "type": "number"
          },
          "distance": {
            "type": "number"
          }
        },
        "required": [
          "azimuth_dd",
          "distance"
        ]
      },
      "description": "List of traverse legs."
    },
    "method": {
      "type": "string",
      "enum": [
        "compass",
        "transit"
      ],
      "description": "Adjustment method (default 'compass')."
    },
    "tolerance": {
      "type": "number",
      "description": "Precision warning threshold (default 1/5000)."
    }
  },
  "required": [
    "legs"
  ]
}
```

---

## `surveying_area_coordinates`

Compute the area of a closed polygon using the coordinate (Shoelace /
Gauss) formula.

Each point requires 'northing' and 'easting' (m).
Minimum 3 points required.

Returns area_m2 in square metres.

Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "points": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "northing": {
            "type": "number"
          },
          "easting": {
            "type": "number"
          }
        },
        "required": [
          "northing",
          "easting"
        ]
      },
      "description": "Polygon vertices (at least 3)."
    }
  },
  "required": [
    "points"
  ]
}
```

---

## `surveying_area_dmd`

Compute the area of a closed traverse polygon using the Double
Meridian Distance (DMD) method.

Each point requires 'northing' and 'easting' (m).
Minimum 3 points required.

Returns area_m2 and per-leg DMD contributions.

Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "points": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "northing": {
            "type": "number"
          },
          "easting": {
            "type": "number"
          }
        },
        "required": [
          "northing",
          "easting"
        ]
      },
      "description": "Polygon vertices (at least 3)."
    }
  },
  "required": [
    "points"
  ]
}
```

---

## `surveying_poi`

Compute the point of intersection of two azimuth rays, each emitted
from a known station.

Provide azimuth1_dd, n1, e1 for station 1 and azimuth2_dd, n2, e2
for station 2.

Returns northing, easting, distance_from_1, distance_from_2.

Errors: {ok:false, reason} if rays are parallel. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "azimuth1_dd": {
      "type": "number",
      "description": "Azimuth from station 1 (decimal degrees)."
    },
    "n1": {
      "type": "number",
      "description": "Station 1 northing (m)."
    },
    "e1": {
      "type": "number",
      "description": "Station 1 easting (m)."
    },
    "azimuth2_dd": {
      "type": "number",
      "description": "Azimuth from station 2 (decimal degrees)."
    },
    "n2": {
      "type": "number",
      "description": "Station 2 northing (m)."
    },
    "e2": {
      "type": "number",
      "description": "Station 2 easting (m)."
    }
  },
  "required": [
    "azimuth1_dd",
    "n1",
    "e1",
    "azimuth2_dd",
    "n2",
    "e2"
  ]
}
```

---

## `surveying_resection`

Compute the position of an unknown instrument station from horizontal
angle observations to three known control points (Tienstra method).

p_known: list of 3 dicts with 'northing' and 'easting' (m).
obs_angles: [alpha, beta] in decimal degrees:
  alpha = horizontal angle A→instrument→B
  beta  = horizontal angle B→instrument→C

Returns northing and easting of the instrument station.

Errors: {ok:false, reason} for degenerate geometry (danger circle).
Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p_known": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "northing": {
            "type": "number"
          },
          "easting": {
            "type": "number"
          }
        },
        "required": [
          "northing",
          "easting"
        ]
      },
      "description": "Exactly 3 known control points [A, B, C]."
    },
    "obs_angles": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Exactly 2 observed angles [alpha, beta] in decimal degrees."
    }
  },
  "required": [
    "p_known",
    "obs_angles"
  ]
}
```

---

## `surveying_level_loop`

Adjust a closed level loop by distributing the elevation misclosure
proportionally to each leg's sight distance.

Each observation requires 'distance' (m) and 'delta_h' (m, +ve = rise).
known_elev is the benchmark elevation in metres.

Returns misclosure, adjusted elevations at each station, and
per-observation corrections.

Errors: {ok:false, reason}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "observations": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "distance": {
            "type": "number"
          },
          "delta_h": {
            "type": "number"
          }
        },
        "required": [
          "distance",
          "delta_h"
        ]
      },
      "description": "Level loop observations."
    },
    "known_elev": {
      "type": "number",
      "description": "Starting benchmark elevation (m)."
    }
  },
  "required": [
    "observations",
    "known_elev"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
