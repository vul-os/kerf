# hydrology

*Module: `kerf_cad_core.hydrology.tools` · Domain: cad*

This module registers **9** LLM tool(s):

- [`hydrology_rational_peak_flow`](#hydrology-rational-peak-flow)
- [`hydrology_composite_runoff_coeff`](#hydrology-composite-runoff-coeff)
- [`hydrology_scs_runoff_depth`](#hydrology-scs-runoff-depth)
- [`hydrology_scs_peak_flow`](#hydrology-scs-peak-flow)
- [`hydrology_time_of_concentration`](#hydrology-time-of-concentration)
- [`hydrology_idf_intensity`](#hydrology-idf-intensity)
- [`hydrology_detention_storage`](#hydrology-detention-storage)
- [`hydrology_storage_indication_route`](#hydrology-storage-indication-route)
- [`hydrology_storm_sewer_pipe_size`](#hydrology-storm-sewer-pipe-size)

---

## `hydrology_rational_peak_flow`

Compute the rational-method peak stormwater flow.

Formula:  Q = C · i · A / 360
  Q in m³/s,  i in mm/hr,  A in ha.

The Rational Method is applicable to urban catchments < ~80 ha with
time of concentration < ~3 hr.  Use a composite C for mixed land use.

Returns Q_m3s and Q_L_per_s.

Reference: ASCE/EWRI 45-05.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "C": {
      "type": "number",
      "description": "Runoff coefficient (0 < C \u2264 1.0). Typical: 0.90 impervious, 0.35 lawn."
    },
    "i_mm_hr": {
      "type": "number",
      "description": "Design rainfall intensity (mm/hr) for the return period and storm duration equal to tc."
    },
    "A_ha": {
      "type": "number",
      "description": "Catchment area (ha)."
    }
  },
  "required": [
    "C",
    "i_mm_hr",
    "A_ha"
  ]
}
```

---

## `hydrology_composite_runoff_coeff`

Compute an area-weighted composite runoff coefficient C for a catchment
with multiple land-cover types.

C_composite = Σ(C_i × A_i) / Σ(A_i)

Returns C_composite and total_area_ha.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "areas": {
      "type": "array",
      "description": "List of sub-area objects, each: {C: number (0\u20131), area_ha: number (> 0)}.",
      "items": {
        "type": "object",
        "properties": {
          "C": {
            "type": "number"
          },
          "area_ha": {
            "type": "number"
          }
        },
        "required": [
          "C",
          "area_ha"
        ]
      }
    }
  },
  "required": [
    "areas"
  ]
}
```

---

## `hydrology_scs_runoff_depth`

Compute the SCS/NRCS curve-number runoff depth.

SCS equations (NEH-630, TR-55):
  S = 25400/CN − 254    (potential maximum retention, mm)
  Ia = 0.2 × S          (initial abstraction, mm)
  Q = (P − Ia)² / (P − Ia + S)   for P > Ia, else 0

CN ranges: 30 (good woods, low runoff) to 98 (impervious pavement).
AMC-II (average moisture) is assumed.

Returns Q_mm (runoff depth), S_mm, Ia_mm.

Reference: USDA NRCS NEH Part 630, Chapter 10 (2004).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "P_mm": {
      "type": "number",
      "description": "Total storm rainfall (mm), >= 0."
    },
    "CN": {
      "type": "number",
      "description": "SCS runoff curve number (1\u2013100)."
    }
  },
  "required": [
    "P_mm",
    "CN"
  ]
}
```

---

## `hydrology_scs_peak_flow`

Compute the SCS/TR-55 graphical-peak flow for a small watershed.

Procedure (TR-55 Chapter 4):
  1. Compute runoff depth Q from CN and P.
  2. Compute Ia/P ratio.
  3. Interpolate unit peak discharge qu from TR-55 Appendix B
     (tabulated by tc and Ia/P).
  4. Qp = qu × A × Q.

Valid range: tc 0.1–2.0 hr; drainage areas < ~25 km²;
24-hour Type II/III rainfall distribution.

Returns Qp_m3s, Q_mm, qu, Ia_P_ratio.

Reference: USDA SCS TR-55 (1986), Chapter 4.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "CN": {
      "type": "number",
      "description": "SCS runoff curve number (1\u2013100)."
    },
    "A_km2": {
      "type": "number",
      "description": "Drainage area (km\u00b2), > 0."
    },
    "tc_hr": {
      "type": "number",
      "description": "Time of concentration (hr). TR-55 valid range: 0.1\u20132.0 hr."
    },
    "P_mm": {
      "type": "number",
      "description": "24-hour design rainfall (mm), > 0."
    }
  },
  "required": [
    "CN",
    "A_km2",
    "tc_hr",
    "P_mm"
  ]
}
```

---

## `hydrology_time_of_concentration`

Compute the time of concentration (tc) using one of three methods.

Methods:

'kirpich' — Kirpich (1940) formula for small agricultural watersheds:
    tc [min] = 0.0195 × L^0.77 × S^-0.385;  S = H/L.
    Inputs: L_m (channel length, m), H_m (elevation drop, m).

'nrcs_velocity' — NRCS velocity method (TR-55 §3.2):
    V = k × sqrt(slope)  [ft/s, converted internally];
    tc = L / V.
    Inputs: L_m, slope (m/m), cover (land cover type string).
    Valid cover types: forest_with_litter, range_grass, short_grass_pasture,
    cultivated_straight_rows, nearly_bare_fallow, grassed_waterway,
    paved_gutter, concrete_channel.

'sheet_shallow_channel' — TR-55 three-segment method (§3.1–3.3):
    Segment 1 (sheet flow): TR-55 Eq. 3-3.
    Segment 2 (shallow concentrated): NRCS velocity.
    Segment 3 (channel): Manning's equation.
    Inputs: sheet_length_m, sheet_n, sheet_P2_mm, sheet_slope,
            shallow_length_m, shallow_slope, shallow_cover,
            channel_length_m, channel_slope, channel_area_m2,
            channel_wetted_perim_m, channel_n.

Returns tc_hr, tc_min, method, warnings (and method-specific sub-times).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "method": {
      "type": "string",
      "enum": [
        "kirpich",
        "nrcs_velocity",
        "sheet_shallow_channel"
      ],
      "description": "Time-of-concentration method."
    },
    "L_m": {
      "type": "number",
      "description": "Flow/channel length (m)."
    },
    "H_m": {
      "type": "number",
      "description": "Elevation drop (m). Kirpich only."
    },
    "slope": {
      "type": "number",
      "description": "Average slope (m/m). nrcs_velocity only."
    },
    "cover": {
      "type": "string",
      "description": "Land cover type. nrcs_velocity only."
    },
    "sheet_length_m": {
      "type": "number"
    },
    "sheet_n": {
      "type": "number",
      "description": "Manning n for sheet flow."
    },
    "sheet_P2_mm": {
      "type": "number",
      "description": "2-yr 24-hr rainfall (mm)."
    },
    "sheet_slope": {
      "type": "number"
    },
    "shallow_length_m": {
      "type": "number"
    },
    "shallow_slope": {
      "type": "number"
    },
    "shallow_cover": {
      "type": "string"
    },
    "channel_length_m": {
      "type": "number"
    },
    "channel_slope": {
      "type": "number"
    },
    "channel_area_m2": {
      "type": "number",
      "description": "Channel cross-section area (m\u00b2)."
    },
    "channel_wetted_perim_m": {
      "type": "number",
      "description": "Channel wetted perimeter (m)."
    },
    "channel_n": {
      "type": "number",
      "description": "Manning n for channel."
    }
  },
  "required": [
    "method"
  ]
}
```

---

## `hydrology_idf_intensity`

Compute design rainfall intensity from a fitted IDF (Intensity-Duration-
Frequency) formula.

Formula:  i = a / (t + b)^c   [mm/hr]
  t = storm duration (min)
  a, b, c = site-specific regression coefficients

The parameters a, b, c are obtained by fitting regional IDF data
(e.g. NOAA Atlas 14, SANRAL TRH 16, or similar) for the required
return period.

Returns intensity_mm_hr.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "duration_min": {
      "type": "number",
      "description": "Storm duration / time of concentration (min), > 0."
    },
    "a": {
      "type": "number",
      "description": "IDF scale coefficient (mm/hr \u00b7 min^c), > 0."
    },
    "b": {
      "type": "number",
      "description": "IDF time offset (min), >= 0."
    },
    "c": {
      "type": "number",
      "description": "IDF decay exponent (dimensionless), > 0."
    }
  },
  "required": [
    "duration_min",
    "a",
    "b",
    "c"
  ]
}
```

---

## `hydrology_detention_storage`

Estimate required detention basin storage volume by the modified-rational
method.

V ≈ 0.5 × (Q_in − Q_out) × tc × 3600   [m³]
(triangular hydrograph approximation)

Applicable to small urban catchments (A < ~80 ha, tc < 3 hr) where the
rational method is valid.

Returns V_m3 (required storage volume).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q_in_cms": {
      "type": "number",
      "description": "Pre-development or design-storm peak inflow (m\u00b3/s)."
    },
    "Q_out_cms": {
      "type": "number",
      "description": "Allowable release rate / outflow (m\u00b3/s)."
    },
    "tc_hr": {
      "type": "number",
      "description": "Time of concentration (hr)."
    }
  },
  "required": [
    "Q_in_cms",
    "Q_out_cms",
    "tc_hr"
  ]
}
```

---

## `hydrology_storage_indication_route`

Route an inflow hydrograph through a detention basin using the
storage-indication (Puls / level-pool) method.

Routing equation (continuity, Δt time step):
    (S/Δt + O/2)|₂ = (I₁ + I₂)/2 + (S/Δt − O/2)|₁

Outflow is obtained from the user-supplied stage-storage-outflow
rating table {storage_m3, outflow_m3s} via linear interpolation.

Warns if storage exceeds the rating table (overtopping risk).

Returns outflow hydrograph (outflow_m3s list), storage time series
(storage_m3 list), peak_outflow_m3s, peak_storage_m3.

Reference: Chow, Maidment & Mays (1988) — Applied Hydrology, §8.4.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "inflow_series": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Inflow hydrograph ordinates (m\u00b3/s) at uniform time step dt_s."
    },
    "outflow_rating": {
      "type": "array",
      "description": "Stage-storage-outflow table sorted by storage_m3 ascending. Each entry: {storage_m3: number, outflow_m3s: number}.",
      "items": {
        "type": "object",
        "properties": {
          "storage_m3": {
            "type": "number"
          },
          "outflow_m3s": {
            "type": "number"
          }
        },
        "required": [
          "storage_m3",
          "outflow_m3s"
        ]
      }
    },
    "dt_s": {
      "type": "number",
      "description": "Time step (s), > 0."
    },
    "S0_m3": {
      "type": "number",
      "description": "Initial basin storage (m\u00b3, default 0)."
    }
  },
  "required": [
    "inflow_series",
    "outflow_rating",
    "dt_s"
  ]
}
```

---

## `hydrology_storm_sewer_pipe_size`

Select the minimum standard circular storm-sewer pipe diameter
using Manning's full-flow equation.

Manning full-flow:  Q = (1/n) · (π/4)·D² · (D/4)^(2/3) · S^(1/2)

The smallest standard diameter (from the ASTM/ISO nominal series)
where Q_full ≥ Q_design / freeboard_fraction is selected.
If no standard size fits, the minimum required diameter is computed
analytically and a warning is issued.

Warns on: undersized pipe, freeboard exceedance, velocity below
self-cleansing threshold (0.6 m/s).

Returns diameter_m, diameter_mm, Q_full_m3s, utilisation, freeboard_ok.

Reference: ASCE MOP 36 (2007); Ven Te Chow (1959).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q_cms": {
      "type": "number",
      "description": "Design peak flow (m\u00b3/s), > 0."
    },
    "slope": {
      "type": "number",
      "description": "Hydraulic gradient (m/m), > 0."
    },
    "n": {
      "type": "number",
      "description": "Manning's roughness coefficient (default 0.013 for concrete). Typical: 0.010 PVC, 0.011 HDPE, 0.013 concrete/clay."
    },
    "min_d_m": {
      "type": "number",
      "description": "Minimum acceptable diameter (m, default 0.15 m = 150 mm)."
    },
    "max_d_m": {
      "type": "number",
      "description": "Maximum diameter to consider (m, default 3.0 m)."
    },
    "freeboard_fraction": {
      "type": "number",
      "description": "Ratio of design flow to full-flow capacity (default 0.85). E.g. 0.85 means pipe designed to flow 85% full."
    }
  },
  "required": [
    "Q_cms",
    "slope"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
