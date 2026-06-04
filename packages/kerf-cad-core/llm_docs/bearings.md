# bearings

*Module: `kerf_cad_core.bearings.tools` · Domain: cad*

This module registers **10** LLM tool(s):

- [`bearing_equivalent_load`](#bearing-equivalent-load)
- [`bearing_rating_life`](#bearing-rating-life)
- [`bearing_adjusted_life`](#bearing-adjusted-life)
- [`bearing_static_safety`](#bearing-static-safety)
- [`bearing_required_capacity`](#bearing-required-capacity)
- [`bearing_limiting_speed`](#bearing-limiting-speed)
- [`bearing_grease_interval`](#bearing-grease-interval)
- [`bearing_select`](#bearing-select)
- [`bearing_aiso_factor`](#bearing-aiso-factor)
- [`bearing_modified_reference_life`](#bearing-modified-reference-life)

---

## `bearing_equivalent_load`

Compute the equivalent dynamic bearing load P = X·Fr + Y·Fa per ISO 281.

For deep-groove ball bearings (bearing_type='ball'), X and Y are
interpolated from the ISO 281 Table 4 e-ratio table based on Fa/C0.
  if Fa/Fr <= e → P = 1·Fr + 0·Fa  (radial load governs)
  else          → P = X·Fr + Y·Fa  (axial load significant)

For roller bearings (cylindrical NU/N series) axial load is ignored:
  P = Fr.

Returns P_N, X, Y, e, and any warnings.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Fr": {
      "type": "number",
      "description": "Radial force (N). Must be >= 0."
    },
    "Fa": {
      "type": "number",
      "description": "Axial force (N). Must be >= 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "angular-contact",
        "roller"
      ],
      "description": "Bearing type: 'ball' (deep-groove, default), 'angular-contact' (25\u00b0 contact angle), 'roller' (cylindrical)."
    },
    "C0": {
      "type": "number",
      "description": "Basic static load rating (N). Used for Fa/C0 ratio in the ISO 281 Table 4 interpolation for ball bearings. If omitted, conservative defaults are applied."
    }
  },
  "required": [
    "Fr",
    "Fa"
  ]
}
```

---

## `bearing_rating_life`

Compute the ISO 281 basic rating life L10 for a rolling bearing.

L10 is the life exceeded by 90% of a batch of identical bearings.

  ball bearing:   L10 = (C/P)³        [10⁶ rev]
  roller bearing: L10 = (C/P)^(10/3)  [10⁶ rev]

If n_rpm is supplied, L10_hours is also returned.

Returns L10_rev, optionally L10_hours, C_over_P ratio, and warnings.
Warns if C/P < 1.0 (under-capacity).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "C": {
      "type": "number",
      "description": "Basic dynamic load rating (N). From bearing data sheet. Must be > 0."
    },
    "P": {
      "type": "number",
      "description": "Equivalent dynamic bearing load (N). Use bearing_equivalent_load tool to compute. Must be > 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type: 'ball' (p=3, default) or 'roller' (p=10/3)."
    },
    "n_rpm": {
      "type": "number",
      "description": "Operating speed (rpm). When provided, L10_hours is returned. Must be > 0 if supplied."
    }
  },
  "required": [
    "C",
    "P"
  ]
}
```

---

## `bearing_adjusted_life`

Compute the ISO 281 adjusted (modified) rating life.

  Lna = a1 × a23 × L10          [10⁶ rev]
  Lna_hours = Lna × 10⁶ / (60·n)

a1 — reliability factor:
  1.00 → 90% reliability (standard L10)
  0.62 → 95% reliability (L5)
  0.44 → 97% reliability (L3)
  0.21 → 99% reliability (L1)

a23 — combined lubrication + contamination factor; typical 0.5–3.0.
      Default 1.0 (ISO 281 simplified method, neutral).

Returns L10_rev, Lna_rev, L10_hours, Lna_hours, and warnings.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "C": {
      "type": "number",
      "description": "Basic dynamic load rating (N). Must be > 0."
    },
    "P": {
      "type": "number",
      "description": "Equivalent dynamic bearing load (N). Must be > 0."
    },
    "n_rpm": {
      "type": "number",
      "description": "Operating speed (rpm). Must be > 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type: 'ball' (default) or 'roller'."
    },
    "a1": {
      "type": "number",
      "description": "Reliability factor per ISO 281 Table 1. 1.00=90% (default), 0.62=95%, 0.44=97%, 0.21=99%."
    },
    "a23": {
      "type": "number",
      "description": "Lubrication / contamination / material factor. Default 1.0. Values > 1 improve life; < 1 reduce life."
    }
  },
  "required": [
    "C",
    "P",
    "n_rpm"
  ]
}
```

---

## `bearing_static_safety`

Compute the static safety factor s0 = C0 / P0 per ISO 76.

Minimum recommended s0 values (SKF):
  s0 >= 0.8 — smooth vibration-free conditions
  s0 >= 1.0 — normal conditions
  s0 >= 1.5 — moderate shock / vibration
  s0 >= 2.0 — heavy shock

Returns s0 and warning flags for under-safety conditions.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "C0": {
      "type": "number",
      "description": "Basic static load rating (N). Must be > 0."
    },
    "P0": {
      "type": "number",
      "description": "Equivalent static load (N). For ball: P0 = 0.6\u00b7Fr + 0.5\u00b7Fa; use max(P0, Fr). Must be > 0."
    }
  },
  "required": [
    "C0",
    "P0"
  ]
}
```

---

## `bearing_required_capacity`

Compute the required basic dynamic load rating C for a target life.

Inverts the adjusted-life equation:
  C = P × (Lh_target × 60 × n / (a1 × a23 × 10⁶))^(1/p)

Use this to find the minimum C when selecting a bearing from a catalogue.

Returns C_required_N (N).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "P": {
      "type": "number",
      "description": "Equivalent dynamic bearing load (N). Must be > 0."
    },
    "n_rpm": {
      "type": "number",
      "description": "Operating speed (rpm). Must be > 0."
    },
    "Lh_target": {
      "type": "number",
      "description": "Target adjusted rating life (hours). Must be > 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type: 'ball' (default) or 'roller'."
    },
    "a1": {
      "type": "number",
      "description": "Reliability factor (default 1.0 = L10 = 90%)."
    },
    "a23": {
      "type": "number",
      "description": "Lubrication / material factor (default 1.0)."
    }
  },
  "required": [
    "P",
    "n_rpm",
    "Lh_target"
  ]
}
```

---

## `bearing_limiting_speed`

Evaluate the n·dm speed parameter (mm·rpm) against catalogue limits.

SKF grease-lubrication limits:
  deep-groove ball bearing: 600 000 mm·rpm
  cylindrical roller:       300 000 mm·rpm

dm_mm = (bore + OD) / 2  (pitch diameter in mm).

Returns ndm, ndm_limit, utilisation fraction, and over-speed warnings.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "dm_mm": {
      "type": "number",
      "description": "Pitch diameter (bore + OD) / 2 in mm. Must be > 0."
    },
    "n_rpm": {
      "type": "number",
      "description": "Operating speed (rpm). Must be > 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type: 'ball' (default) or 'roller'."
    }
  },
  "required": [
    "dm_mm",
    "n_rpm"
  ]
}
```

---

## `bearing_grease_interval`

Estimate the grease relubrication interval in hours (SKF handbook method).

  tf = K × (14×10⁶ / (n × √dm) − 4×dm)   [hours, base formula]

A load correction factor (C/P)^0.3 is applied; higher C/P gives a
longer relubrication interval.

Applicable when n·√dm < 14×10⁶; otherwise continuous oil lubrication
is recommended (returns 0 hours with a warning).

Load inputs C_kN and P_kN are in kilonewtons (SKF formula convention).

Returns relubrication_hours and warnings.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "dm_mm": {
      "type": "number",
      "description": "Pitch diameter (mm). Must be > 0."
    },
    "n_rpm": {
      "type": "number",
      "description": "Operating speed (rpm). Must be > 0."
    },
    "C_kN": {
      "type": "number",
      "description": "Basic dynamic load rating (kN). Must be > 0."
    },
    "P_kN": {
      "type": "number",
      "description": "Equivalent dynamic load (kN). Must be > 0."
    }
  },
  "required": [
    "dm_mm",
    "n_rpm",
    "C_kN",
    "P_kN"
  ]
}
```

---

## `bearing_select`

Select the lightest bearing from a built-in series table that meets
the target adjusted life and static safety requirements.

Available series:
  '6000' — SKF 6000 deep-groove ball (bore 10–50 mm)
  '6200' — SKF 6200 deep-groove ball (bore 10–50 mm)
  '6300' — SKF 6300 deep-groove ball (bore 10–50 mm)
  'NU200' — SKF NU 200 cylindrical roller (bore 15–70 mm)

Returns the selected bearing data dict (or null if none qualifies),
plus a list of all candidates with their computed adjusted life.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "series": {
      "type": "string",
      "enum": [
        "6000",
        "6200",
        "6300",
        "NU200"
      ],
      "description": "Bearing series to search."
    },
    "Fr": {
      "type": "number",
      "description": "Radial force (N). Must be >= 0."
    },
    "Fa": {
      "type": "number",
      "description": "Axial force (N). Must be >= 0."
    },
    "n_rpm": {
      "type": "number",
      "description": "Operating speed (rpm). Must be > 0."
    },
    "Lh_min": {
      "type": "number",
      "description": "Minimum required adjusted life (hours). Must be > 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type: 'ball' (default) or 'roller'."
    },
    "a1": {
      "type": "number",
      "description": "Reliability factor (default 1.0 = L10)."
    },
    "a23": {
      "type": "number",
      "description": "Lubrication / material factor (default 1.0)."
    },
    "s0_min": {
      "type": "number",
      "description": "Minimum required static safety factor (default 1.0)."
    }
  },
  "required": [
    "series",
    "Fr",
    "Fa",
    "n_rpm",
    "Lh_min"
  ]
}
```

---

## `bearing_aiso_factor`

Compute the ISO/TS 16281 life-modification factor aISO.

aISO incorporates lubrication quality (viscosity ratio κ) and contamination level (eC) to modify the basic ISO 281 rating life:
  Lnm = a1 · aISO · L10

Implements SKF Method B (ISO/TS 16281:2008 §5.4). Range: 0.1–50.

  κ < 1    → thin-film lubrication → reduced life
  eC = 1   → perfectly clean conditions
  eC = 0.2 → typical industrial gearbox

Reference: ISO/TS 16281:2008 §5.4; SKF catalogue §17.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "kappa": {
      "type": "number",
      "description": "Viscosity ratio \u03ba = \u03bd_actual / \u03bd1_required. \u03ba < 1 = thin film; \u03ba >= 4 = full film."
    },
    "eC": {
      "type": "number",
      "description": "Contamination factor (0 < eC <= 1). 1.0 = very clean; 0.5 = slight; 0.1 = heavy."
    },
    "Cu_N": {
      "type": "number",
      "description": "Bearing fatigue load limit Cu (N). From bearing catalogue."
    },
    "P_N": {
      "type": "number",
      "description": "Equivalent dynamic bearing load P (N). Must be > 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type. Default 'ball'."
    }
  },
  "required": [
    "kappa",
    "eC",
    "Cu_N",
    "P_N"
  ]
}
```

---

## `bearing_modified_reference_life`

Compute the ISO/TS 16281 modified reference rating life Lnm.

Lnm = a1 · aISO · L10   [10^6 rev]
Lnm_hours = Lnm × 10^6 / (60 × n_rpm)

Extends the basic ISO 281 L10 with the aISO life-modification factor that accounts for lubrication quality (κ) and contamination (eC).

Example (SKF): C=60kN, P=10kN, n=1500rpm, κ=1.5, eC=0.5, Cu=4.5kN, ball → aISO≈2.5, Lnm_hours significantly above L10_hours.

Reference: ISO/TS 16281:2008 §3, §5; SKF catalogue §17 Eq. (15.1).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "C": {
      "type": "number",
      "description": "Basic dynamic load rating (N)."
    },
    "P": {
      "type": "number",
      "description": "Equivalent dynamic bearing load (N)."
    },
    "n_rpm": {
      "type": "number",
      "description": "Operating speed (rpm)."
    },
    "kappa": {
      "type": "number",
      "description": "Viscosity ratio \u03ba = \u03bd_actual / \u03bd1_required."
    },
    "eC": {
      "type": "number",
      "description": "Contamination factor (0 < eC <= 1)."
    },
    "Cu_N": {
      "type": "number",
      "description": "Bearing fatigue load limit Cu (N). Approx 0.45\u00d7C0 for steel ball."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type. Default 'ball'."
    },
    "a1": {
      "type": "number",
      "description": "Reliability factor a1 (ISO 281 Table 1). 1.0 = 90%, 0.62 = 95%, 0.21 = 99%. Default 1.0."
    },
    "fatigue_limited": {
      "type": "boolean",
      "description": "If true and P < Cu, life is treated as infinite (capped at 50\u00d7L10)."
    }
  },
  "required": [
    "C",
    "P",
    "n_rpm",
    "kappa",
    "eC",
    "Cu_N"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
