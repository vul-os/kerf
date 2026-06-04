# acoustics

*Module: `kerf_cad_core.acoustics.tools` · Domain: cad*

This module registers **24** LLM tool(s):

- [`acoustics_spl_sum`](#acoustics-spl-sum)
- [`acoustics_spl_subtract`](#acoustics-spl-subtract)
- [`acoustics_spl_average`](#acoustics-spl-average)
- [`acoustics_point_source`](#acoustics-point-source)
- [`acoustics_line_source`](#acoustics-line-source)
- [`acoustics_inverse_square`](#acoustics-inverse-square)
- [`acoustics_sabine_rt60`](#acoustics-sabine-rt60)
- [`acoustics_eyring_rt60`](#acoustics-eyring-rt60)
- [`acoustics_room_constant`](#acoustics-room-constant)
- [`acoustics_reverberant_spl`](#acoustics-reverberant-spl)
- [`acoustics_mass_law_tl`](#acoustics-mass-law-tl)
- [`acoustics_composite_tl`](#acoustics-composite-tl)
- [`acoustics_spl_transmitted`](#acoustics-spl-transmitted)
- [`acoustics_a_weighting`](#acoustics-a-weighting)
- [`acoustics_c_weighting`](#acoustics-c-weighting)
- [`acoustics_apply_weighting`](#acoustics-apply-weighting)
- [`acoustics_octave_combine`](#acoustics-octave-combine)
- [`acoustics_nc_rating`](#acoustics-nc-rating)
- [`acoustics_nr_rating`](#acoustics-nr-rating)
- [`acoustics_duct_attenuation`](#acoustics-duct-attenuation)
- [`acoustics_duct_breakout`](#acoustics-duct-breakout)
- [`acoustics_duct_regen`](#acoustics-duct-regen)
- [`acoustics_lw_from_lp`](#acoustics-lw-from-lp)
- [`acoustics_lp_from_lw`](#acoustics-lp-from-lw)

---

## `acoustics_spl_sum`

Logarithmic (energy) sum of multiple sound pressure levels.

Formula: L_total = 10·log₁₀(Σ 10^(Lᵢ/10))

Use when combining SPLs from multiple simultaneous noise sources.
Example: two identical 70 dB sources sum to ≈ 73 dB, not 140 dB.

Errors: {ok:false, reason} for empty list or non-numeric values.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "levels_db": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "List of SPL values in dB. Must contain at least one element."
    }
  },
  "required": [
    "levels_db"
  ]
}
```

---

## `acoustics_spl_subtract`

Subtract a background noise level from a total measurement to recover the source SPL.

Formula: L_source = 10·log₁₀(10^(L_total/10) − 10^(L_bg/10))

Requires spl_total > spl_bg.  Issues a warning if the difference is < 3 dB (high uncertainty region).

Errors: {ok:false, reason} if spl_bg >= spl_total.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "spl_total": {
      "type": "number",
      "description": "Total SPL measured with source present (dB)."
    },
    "spl_bg": {
      "type": "number",
      "description": "Background SPL measured without source (dB)."
    }
  },
  "required": [
    "spl_total",
    "spl_bg"
  ]
}
```

---

## `acoustics_spl_average`

Energy-average (Leq) of multiple sound pressure levels.

Formula: L_avg = 10·log₁₀((1/N) × Σ 10^(Lᵢ/10))

Errors: {ok:false, reason} for empty list.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "levels_db": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "List of SPL values in dB."
    }
  },
  "required": [
    "levels_db"
  ]
}
```

---

## `acoustics_point_source`

Free-field SPL at distance r from a point source (ISO 9613).

Formula: Lp = Lw + 10·log₁₀(Q / (4π r²))

Directivity Q:
  Q=1 → free field (full sphere)
  Q=2 → hemispherical (source on hard floor)
  Q=4 → corner source (two reflecting surfaces)
  Q=8 → three reflecting surfaces

Returns Lp (dB).  Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Lw": {
      "type": "number",
      "description": "Sound power level (dB re 1 pW = 10\u207b\u00b9\u00b2 W)."
    },
    "r": {
      "type": "number",
      "description": "Distance from source to receiver (m). Must be > 0."
    },
    "Q": {
      "type": "number",
      "description": "Directivity factor (default 1.0). Must be > 0."
    }
  },
  "required": [
    "Lw",
    "r"
  ]
}
```

---

## `acoustics_line_source`

SPL at distance r from an infinite coherent line source.

Formula: Lp = Lw/m − 10·log₁₀(2π r)

Applies to roads, railways, pipelines where the source length >> distance.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Lw_per_m": {
      "type": "number",
      "description": "Sound power level per metre of source (dB re 1 pW/m)."
    },
    "r": {
      "type": "number",
      "description": "Perpendicular distance from line to receiver (m). Must be > 0."
    }
  },
  "required": [
    "Lw_per_m",
    "r"
  ]
}
```

---

## `acoustics_inverse_square`

SPL change from distance change for a point source (inverse-square law).

Formula: ΔL = −20·log₁₀(r2 / r1)

Returns ΔL in dB.  Negative result means SPL decreases.
Rule of thumb: 6 dB drop per doubling of distance.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r1": {
      "type": "number",
      "description": "Reference distance (m). Must be > 0."
    },
    "r2": {
      "type": "number",
      "description": "New distance (m). Must be > 0."
    }
  },
  "required": [
    "r1",
    "r2"
  ]
}
```

---

## `acoustics_sabine_rt60`

Sabine reverberation time RT60 for a room.

Formula: RT60 = 0.161 × V / A    (seconds)
where V = room volume (m³), A = total absorption (m² sabins) = Σ(Sᵢ αᵢ).

Applicable for average absorption coefficient < ~0.2 (diffuse field assumption).
For higher absorption use acoustics_eyring_rt60 instead.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "volume_m3": {
      "type": "number",
      "description": "Room volume (m\u00b3). Must be > 0."
    },
    "total_absorption_m2": {
      "type": "number",
      "description": "Total acoustic absorption (m\u00b2). Computed as \u03a3(surface_area_m2 \u00d7 absorption_coefficient). Must be > 0."
    }
  },
  "required": [
    "volume_m3",
    "total_absorption_m2"
  ]
}
```

---

## `acoustics_eyring_rt60`

Eyring reverberation time — more accurate than Sabine for higher absorption.

Formula: RT60 = 0.161 × V / (−S × ln(1 − α_avg))    (seconds)

Recommended when the average absorption coefficient α > 0.2.
alpha_avg must be strictly between 0 and 1.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "volume_m3": {
      "type": "number",
      "description": "Room volume (m\u00b3). Must be > 0."
    },
    "S_m2": {
      "type": "number",
      "description": "Total room surface area (m\u00b2). Must be > 0."
    },
    "alpha_avg": {
      "type": "number",
      "description": "Average absorption coefficient (0 < \u03b1 < 1)."
    }
  },
  "required": [
    "volume_m3",
    "S_m2",
    "alpha_avg"
  ]
}
```

---

## `acoustics_room_constant`

Room constant R used in combined direct + reverberant field SPL calculations.

Formula: R = S × α / (1 − α)    (m²)

Higher R means more absorption (quieter reverberant field).

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "S_m2": {
      "type": "number",
      "description": "Total room surface area (m\u00b2). Must be > 0."
    },
    "alpha_avg": {
      "type": "number",
      "description": "Average absorption coefficient (0 < \u03b1 < 1)."
    }
  },
  "required": [
    "S_m2",
    "alpha_avg"
  ]
}
```

---

## `acoustics_reverberant_spl`

Reverberant-field SPL contribution from a source with known Lw.

Formula: Lp_rev = Lw + 10·log₁₀(4 / R)

Use this to assess the diffuse-field noise level away from direct sound.
Combine with direct-field SPL (acoustics_point_source) for total Lp.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Lw": {
      "type": "number",
      "description": "Sound power level (dB re 1 pW)."
    },
    "R": {
      "type": "number",
      "description": "Room constant R (m\u00b2) from acoustics_room_constant. Must be > 0."
    }
  },
  "required": [
    "Lw",
    "R"
  ]
}
```

---

## `acoustics_mass_law_tl`

Mass-law transmission loss (TL) for a single-leaf partition.

Formula (field-incidence, ISO 140-3):
    TL = 20·log₁₀(m × f) − 47    (dB)

where m = surface density (kg/m²), f = frequency (Hz).
Valid for limp homogeneous panels below the coincidence frequency.
Issues a warning if TL < 0 (formula not applicable at low mass/frequency).

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "surface_density_kg_m2": {
      "type": "number",
      "description": "Surface density (kg/m\u00b2). Must be > 0."
    },
    "freq_hz": {
      "type": "number",
      "description": "Frequency (Hz). Must be > 0."
    }
  },
  "required": [
    "surface_density_kg_m2",
    "freq_hz"
  ]
}
```

---

## `acoustics_composite_tl`

Composite partition transmission loss from multiple parallel elements (e.g. wall with a window and a door).

Each element: {area_m2: <float>, tl_db: <float>}
Formula: τ_avg = Σ(Sᵢ τᵢ)/ΣSᵢ  →  TL = −10·log₁₀(τ_avg)

A single weak element (window) can dominate and reduce overall TL significantly.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "elements": {
      "type": "array",
      "description": "List of partition elements. Each element must have 'area_m2' (m\u00b2) and 'tl_db' (dB).",
      "items": {
        "type": "object",
        "properties": {
          "area_m2": {
            "type": "number"
          },
          "tl_db": {
            "type": "number"
          }
        },
        "required": [
          "area_m2",
          "tl_db"
        ]
      }
    }
  },
  "required": [
    "elements"
  ]
}
```

---

## `acoustics_spl_transmitted`

SPL on the receiving side of a barrier given source-side SPL and TL.

Formula: Lp_transmitted = Lp_source − TL

Issues a warning if tl_db < 0 (physically unusual).

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "spl_source": {
      "type": "number",
      "description": "Source-side SPL (dB)."
    },
    "tl_db": {
      "type": "number",
      "description": "Transmission loss of the barrier (dB). Normally >= 0."
    }
  },
  "required": [
    "spl_source",
    "tl_db"
  ]
}
```

---

## `acoustics_a_weighting`

A-weighting frequency correction at a given frequency (IEC 61672-1).

A-weighting approximates human hearing sensitivity across the audio spectrum.
Add the returned offset_db to the unweighted SPL to obtain dB(A).

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency (Hz). Must be > 0."
    }
  },
  "required": [
    "freq_hz"
  ]
}
```

---

## `acoustics_c_weighting`

C-weighting frequency correction at a given frequency (IEC 61672-1).

C-weighting is nearly flat across the audible range; used for peak sound pressure levels and low-frequency noise assessment.
Add the returned offset_db to the unweighted SPL to obtain dB(C).

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency (Hz). Must be > 0."
    }
  },
  "required": [
    "freq_hz"
  ]
}
```

---

## `acoustics_apply_weighting`

Apply A or C weighting corrections to octave-band SPL measurements.

Accepted octave-band centre frequencies (Hz): 31, 63, 125, 250, 500, 1000, 2000, 4000, 8000, 16000.

Returns a dict of weighted SPL per band.  Follow with acoustics_octave_combine to get a single dB(A) or dB(C) number.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "octave_band_spls": {
      "type": "object",
      "description": "Object mapping centre frequency (Hz) to unweighted SPL (dB). Keys should be integer Hz values as strings or numbers.",
      "additionalProperties": {
        "type": "number"
      }
    },
    "weighting": {
      "type": "string",
      "enum": [
        "A",
        "C"
      ],
      "description": "Weighting network: 'A' (default) or 'C'."
    }
  },
  "required": [
    "octave_band_spls"
  ]
}
```

---

## `acoustics_octave_combine`

Combine weighted octave-band SPL values into a single overall level.

Formula: L_total = 10·log₁₀(Σ 10^(Lᵢ/10))

Typically used after acoustics_apply_weighting to get a single dB(A) value.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "weighted_spls": {
      "type": "object",
      "description": "Object mapping frequency (Hz) to weighted SPL (dB).",
      "additionalProperties": {
        "type": "number"
      }
    }
  },
  "required": [
    "weighted_spls"
  ]
}
```

---

## `acoustics_nc_rating`

Noise Criteria (NC) rating for an octave-band spectrum.

The NC rating is the lowest NC curve that the measured spectrum does not exceed in any octave band (63–8000 Hz).  Range: NC-15 to NC-70.

Typical design targets:
  Private offices / bedrooms: NC-25 to NC-35
  Open offices:               NC-35 to NC-45
  Mechanical rooms:           NC-60 to NC-70

Issues a warning if the spectrum exceeds NC-70.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "octave_band_spls": {
      "type": "object",
      "description": "Object mapping centre frequency (Hz) to SPL (dB). Standard bands: 63, 125, 250, 500, 1000, 2000, 4000, 8000.",
      "additionalProperties": {
        "type": "number"
      }
    }
  },
  "required": [
    "octave_band_spls"
  ]
}
```

---

## `acoustics_nr_rating`

Noise Rating (NR) curve level for an octave-band spectrum (ISO 1996-1).

The NR rating is the lowest NR curve at or above the measured spectrum.
Range: NR-0 to NR-75.

Typical design limits:
  Concert halls:  NR-15 to NR-20
  Offices:        NR-35 to NR-45
  Factories:      NR-65 to NR-75

Issues a warning if the spectrum exceeds NR-75.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "octave_band_spls": {
      "type": "object",
      "description": "Object mapping centre frequency (Hz) to SPL (dB). Standard bands: 63, 125, 250, 500, 1000, 2000, 4000, 8000.",
      "additionalProperties": {
        "type": "number"
      }
    }
  },
  "required": [
    "octave_band_spls"
  ]
}
```

---

## `acoustics_duct_attenuation`

Approximate insertion loss (IL) for a straight HVAC duct section per octave band (ASHRAE 2019, Chapter 48).

Returns per-band IL in dB for the 63–8000 Hz octave bands.

lining options: 'lined' (fibrous insulation inside duct) or 'unlined'.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "length_m": {
      "type": "number",
      "description": "Duct section length (m). Must be > 0."
    },
    "diam_m": {
      "type": "number",
      "description": "Hydraulic diameter (m). Must be > 0."
    },
    "lining": {
      "type": "string",
      "enum": [
        "lined",
        "unlined"
      ],
      "description": "'lined' or 'unlined' (default 'unlined')."
    }
  },
  "required": [
    "length_m",
    "diam_m"
  ]
}
```

---

## `acoustics_duct_breakout`

Breakout noise SPL radiated through a duct wall section (ASHRAE 2019).

Formula: Lp_out = Lw_in − TL + 10·log₁₀(perimeter × length)

Use to assess noise break-out through unlined sheet metal ducts.

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Lw_in": {
      "type": "number",
      "description": "Sound power level inside the duct (dB re 1 pW)."
    },
    "length_m": {
      "type": "number",
      "description": "Duct section length (m). Must be > 0."
    },
    "perimeter_m": {
      "type": "number",
      "description": "Duct cross-section perimeter (m). Must be > 0."
    },
    "tl_db": {
      "type": "number",
      "description": "Transmission loss of the duct wall (dB)."
    }
  },
  "required": [
    "Lw_in",
    "length_m",
    "perimeter_m",
    "tl_db"
  ]
}
```

---

## `acoustics_duct_regen`

Approximate regenerated (self-generated) noise Lw from a duct fitting (ASHRAE 2019, Chapter 48).

Fitting types: 'elbow_90', 'elbow_45', 'tee_branch', 'tee_through', 'reducer', 'diffuser'.

Issues a warning if velocity > 15 m/s (outside typical HVAC design range).

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "velocity_mps": {
      "type": "number",
      "description": "Duct air velocity upstream of fitting (m/s). Must be > 0."
    },
    "diam_m": {
      "type": "number",
      "description": "Duct hydraulic diameter (m). Must be > 0."
    },
    "fitting_type": {
      "type": "string",
      "enum": [
        "elbow_90",
        "elbow_45",
        "tee_branch",
        "tee_through",
        "reducer",
        "diffuser"
      ],
      "description": "Type of fitting (default 'elbow_90')."
    }
  },
  "required": [
    "velocity_mps",
    "diam_m"
  ]
}
```

---

## `acoustics_lw_from_lp`

Estimate sound power level Lw from a measured SPL Lp at distance r.

Formula (free field): Lw = Lp + 10·log₁₀(4π r² / Q)

Assumes free-field conditions (no reverberant build-up).
Q = directivity factor (1=free sphere, 2=hemisphere/hard floor).

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "lp_db": {
      "type": "number",
      "description": "Measured SPL at distance r_m (dB)."
    },
    "r_m": {
      "type": "number",
      "description": "Measurement distance from source (m). Must be > 0."
    },
    "Q": {
      "type": "number",
      "description": "Directivity factor (default 1.0). Must be > 0."
    }
  },
  "required": [
    "lp_db",
    "r_m"
  ]
}
```

---

## `acoustics_lp_from_lw`

Calculate SPL at distance r from sound power level Lw.

Formula: Lp = Lw + 10·log₁₀(Q / (4π r²))

Q = directivity factor:
  Q=1 → free field (full sphere)
  Q=2 → hemispherical (hard floor)
  Q=4 → two perpendicular reflecting surfaces

Errors: {ok:false, reason}.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "lw_db": {
      "type": "number",
      "description": "Sound power level (dB re 1 pW)."
    },
    "r_m": {
      "type": "number",
      "description": "Distance from source to receiver (m). Must be > 0."
    },
    "Q": {
      "type": "number",
      "description": "Directivity factor (default 1.0). Must be > 0."
    }
  },
  "required": [
    "lw_db",
    "r_m"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
