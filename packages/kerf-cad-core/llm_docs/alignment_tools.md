# alignment_tools

*Module: `kerf_cad_core.civil.alignment_tools` · Domain: cad*

This module registers **4** LLM tool(s):

- [`align_horizontal`](#align-horizontal)
- [`align_spiral`](#align-spiral)
- [`align_vertical`](#align-vertical)
- [`align_station_at`](#align-station-at)

---

## `align_horizontal`

Compute a tangent–circular-curve–tangent horizontal road alignment.

Given the intersection (deflection) angle at the PI, the curve radius, and the PI station, this tool returns all standard circular-curve geometry: PC, PT stations, arc length, tangent length, external distance, middle ordinate, long chord, and degree of curve.

Optionally provide design_speed_kmh to get an AASHTO superelevation hint (e + f method, Table 3-7; e clamped to 12% max).

AASHTO relations used:
  L = R·Δ  (arc length, Δ in radians)
  T = R·tan(Δ/2)
  E = R·(sec(Δ/2)−1)
  M = R·(1−cos(Δ/2))
  C = 2·R·sin(Δ/2)
  D = 5729.578/R  (degree of curve)

Errors returned as {ok: false, reason: '...'}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "delta_deg": {
      "type": "number",
      "description": "Intersection (deflection) angle at PI in degrees (0 < delta < 360)."
    },
    "radius_m": {
      "type": "number",
      "description": "Radius of circular curve in metres (> 0)."
    },
    "sta_pi": {
      "type": "string",
      "description": "Station of the PI as a string, e.g. '12+34.56' or '1234.56'."
    },
    "design_speed_kmh": {
      "type": "number",
      "description": "Design speed in km/h for superelevation hint (AASHTO e+f). Omit or set 0 to skip."
    }
  },
  "required": [
    "delta_deg",
    "radius_m",
    "sta_pi"
  ]
}
```

---

## `align_spiral`

Compute a spiralled horizontal alignment with clothoid (Euler spiral) transitions.

Transitions are placed symmetrically: entry spiral (TS→SC), circular arc (SC→CS), exit spiral (CS→ST).

Clothoid geometry (AASHTO / Hickerson):
  θs = Ls/(2·R)                  (spiral angle)
  p  = Ls²/(24·R)               (p-shift, radial offset)
  k  = Ls/2 − Ls³/(240·R²)      (tangent offset)
  Ts = (R+p)·tan(Δ/2) + k       (PI→TS tangent)
  Lc = R·(Δ−2·θs)               (circular arc)

Errors returned as {ok: false, reason: '...'}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "delta_deg": {
      "type": "number",
      "description": "Deflection angle at PI in degrees (> 0)."
    },
    "radius_m": {
      "type": "number",
      "description": "Radius of circular curve in metres (> 0)."
    },
    "spiral_length_m": {
      "type": "number",
      "description": "Length of each transition spiral (metres, > 0)."
    },
    "sta_pi": {
      "type": "string",
      "description": "Station of PI, e.g. '25+00.00'."
    }
  },
  "required": [
    "delta_deg",
    "radius_m",
    "spiral_length_m",
    "sta_pi"
  ]
}
```

---

## `align_vertical`

Compute a parabolic vertical curve for road alignment.

Given back-tangent grade G1, forward-tangent grade G2, the PVI station and elevation, and curve length L, this tool returns:
  - PVC, PVI, PVT stations and elevations
  - K-value (L/A where A = |G2−G1| in %)
  - Crest or sag classification
  - High/low point station and elevation (when G1·G2 < 0)
  - Optional AASHTO sight-distance check

Parabolic elevation formula (AASHTO):
  e(x) = e_PVC + G1·x + (G2−G1)/(2·L)·x²

SSD K_min (AASHTO, S≤L):
  Crest: K_req = S²/(404+3.5·S)
  Sag:   K_req = S²/(120+3.5·S)

Errors returned as {ok: false, reason: '...'}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "grade1": {
      "type": "number",
      "description": "Back-tangent grade (decimal, e.g. 0.04 = +4%)."
    },
    "grade2": {
      "type": "number",
      "description": "Forward-tangent grade (decimal)."
    },
    "sta_pvi": {
      "type": "string",
      "description": "Station of PVI, e.g. '10+00.00'."
    },
    "elev_pvi_m": {
      "type": "number",
      "description": "Elevation of PVI in metres."
    },
    "curve_length_m": {
      "type": "number",
      "description": "Length of vertical curve in metres (> 0)."
    },
    "stopping_sight_distance_m": {
      "type": "number",
      "description": "Stopping sight distance (metres) for AASHTO K check. Omit or 0 to skip."
    }
  },
  "required": [
    "grade1",
    "grade2",
    "sta_pvi",
    "elev_pvi_m",
    "curve_length_m"
  ]
}
```

---

## `align_station_at`

Return the parabolic elevation at any station within a vertical curve.

Provide the curve parameters (PVC station/elevation, grades, length) and a query station; the tool returns the elevation.

Formula: e(x) = e_PVC + G1·x + (G2−G1)/(2·L)·x²
where x = query_station − PVC_station.

Errors returned as {ok: false, reason: '...'}. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sta_pvc": {
      "type": "string",
      "description": "Station of PVC, e.g. '09+50.00'."
    },
    "elev_pvc_m": {
      "type": "number",
      "description": "Elevation at PVC in metres."
    },
    "grade1": {
      "type": "number",
      "description": "Back-tangent grade (decimal)."
    },
    "grade2": {
      "type": "number",
      "description": "Forward-tangent grade (decimal)."
    },
    "curve_length_m": {
      "type": "number",
      "description": "Curve length in metres (> 0)."
    },
    "query_sta": {
      "type": "string",
      "description": "Query station, e.g. '10+00.00'."
    }
  },
  "required": [
    "sta_pvc",
    "elev_pvc_m",
    "grade1",
    "grade2",
    "curve_length_m",
    "query_sta"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
