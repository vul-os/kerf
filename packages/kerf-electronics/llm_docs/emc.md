# emc

*Module: `kerf_electronics.emc.tools` · Domain: electronics*

This module registers **5** LLM tool(s):

- [`emc_radiated_differential`](#emc-radiated-differential)
- [`emc_radiated_common_mode`](#emc-radiated-common-mode)
- [`emc_emission_margin`](#emc-emission-margin)
- [`emc_near_field_crosstalk`](#emc-near-field-crosstalk)
- [`emc_shielding`](#emc-shielding)

---

## `emc_radiated_differential`

Estimate far-field radiated E-field (dBμV/m) from a differential-mode current loop on a PCB.

Model: small-loop (magnetic dipole) far-field approximation from Ott 'Electromagnetic Compatibility Engineering' (Wiley 2009) §6.2:
  E [V/m] = 263e-16 × f² × A × I / r

Valid in the far field (r > λ/(2π)).  A warning is issued when the measurement distance is in the near field.

Input: { freq_hz, loop_area_m2, current_a, distance_m? }
Returns: { ok, e_field_vpm, e_field_dbuvm, far_field, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "loop_area_m2": {
      "type": "number",
      "description": "Enclosed loop area [m\u00b2].  For a PCB trace-return path rectangle of dimensions L \u00d7 W: area = L \u00d7 W (convert mm\u00b2 \u2192 m\u00b2 by \u00f7 1e6)."
    },
    "current_a": {
      "type": "number",
      "description": "Loop current amplitude [A] (peak or RMS)."
    },
    "distance_m": {
      "type": "number",
      "description": "Measurement distance [m] (default 3.0 m)."
    }
  },
  "required": [
    "freq_hz",
    "loop_area_m2",
    "current_a"
  ]
}
```

---

## `emc_radiated_common_mode`

Estimate far-field radiated E-field (dBμV/m) from common-mode current on a cable or PCB trace.

Model: short-monopole (long-wire) antenna approximation from Ott §6.3 / Paul 'Introduction to EMC' (2006) §10.5:
  E [V/m] = μ₀ × f × I_cm × L / r  (= 1.257e-6 × f × I_cm × L / r)

Conservative (worst-case) for electrically short cables (L < λ/4).
A warning is issued when the cable exceeds λ/4.

Input: { freq_hz, cable_length_m, current_a, distance_m? }
Returns: { ok, e_field_vpm, e_field_dbuvm, electrically_short, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "cable_length_m": {
      "type": "number",
      "description": "Cable (or trace) length [m]."
    },
    "current_a": {
      "type": "number",
      "description": "Common-mode current amplitude [A]."
    },
    "distance_m": {
      "type": "number",
      "description": "Measurement distance [m] (default 3.0 m)."
    }
  },
  "required": [
    "freq_hz",
    "cable_length_m",
    "current_a"
  ]
}
```

---

## `emc_emission_margin`

Compare an estimated E-field to FCC Part 15 or CISPR 22/32 radiated emission limit lines and return the margin in dBμV/m.

Positive margin = emission is below limit (compliant).  Negative margin = exceedance; a warning is also issued.

FCC Part 15 §15.109 limits: Class A at 10 m; Class B at 3 m.
CISPR 32:2015 limits: both classes referenced to 10 m.
Distance adjustments use 20×log10(d_ref / d) free-space scaling.

Input: { e_field_dbuvm, freq_hz, standard?, class_?, distance_m? }
Returns: { ok, margin_db, passes, limit_dbuvm, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "e_field_dbuvm": {
      "type": "number",
      "description": "Estimated E-field [dB\u03bcV/m] at the measurement distance."
    },
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "standard": {
      "type": "string",
      "enum": [
        "fcc",
        "cispr"
      ],
      "description": "Regulatory standard: 'fcc' or 'cispr' (default 'cispr')."
    },
    "class_": {
      "type": "string",
      "enum": [
        "A",
        "B"
      ],
      "description": "Emission class: 'A' (commercial/industrial) or 'B' (residential, default)."
    },
    "distance_m": {
      "type": "number",
      "description": "Measurement distance [m] (default 10.0 m)."
    }
  },
  "required": [
    "e_field_dbuvm",
    "freq_hz"
  ]
}
```

---

## `emc_near_field_crosstalk`

Estimate the near-field capacitive + inductive coupling coefficient between two parallel PCB traces (EMC pre-compliance screening).

Model: first-order proximity coupling from Paul 'Introduction to EMC' (2006) §6.3.  Distinct from the SI crosstalk tools which use a coupled-line model; this tool returns a combined dimensionless coupling coefficient K_effective suitable for EMC budgeting.

  Kc ≈ 1 / (1 + (dist/w)²)      — capacitive
  Kl ≈ 1 / (1 + (2×dist/h)²)    — inductive
  K_combined = sqrt(Kc² + Kl²)
  K_effective = K_combined × tanh(L / (100×h))  — length saturation

Input: { freq_hz, trace_width_mm, trace_spacing_mm, trace_height_mm, parallel_length_mm, er? }
Returns: { ok, Kc, Kl, K_combined, K_effective, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "trace_width_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "trace_spacing_mm": {
      "type": "number",
      "description": "Edge-to-edge spacing between the two traces [mm]."
    },
    "trace_height_mm": {
      "type": "number",
      "description": "Trace height above nearest ground plane [mm]."
    },
    "parallel_length_mm": {
      "type": "number",
      "description": "Parallel run length [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity (default 4.5 for FR4)."
    }
  },
  "required": [
    "freq_hz",
    "trace_width_mm",
    "trace_spacing_mm",
    "trace_height_mm",
    "parallel_length_mm"
  ]
}
```

---

## `emc_shielding`

Compute shielding effectiveness (SE) of a conductive enclosure.

Model: Schelkunoff theory (Ott 2009 §5.3-5.4):
  SEa [dB] = 131.4 × t × sqrt(f × μr × σr)    — absorption
  SEr [dB] = 168 + 10×log10(σr / (μr × f))     — reflection (plane wave)
  SE_total = SEa + SEr − SE_multiple
  SE_aperture [dB] = 20×log10(c / (2 × f × L_slot))  — slot leakage
  SE_effective = min(SE_total, SE_aperture) when aperture present

Input: { freq_hz, thickness_m, conductivity_relative?, permeability_relative?, aperture_length_m? }
Returns: { ok, se_absorption_db, se_reflection_db, se_total_db, se_effective_db, aperture_limited, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "thickness_m": {
      "type": "number",
      "description": "Enclosure wall thickness [m]."
    },
    "conductivity_relative": {
      "type": "number",
      "description": "Relative conductivity \u03c3r (copper = 1.0, aluminium \u2248 0.61, steel \u2248 0.10).  Default 1.0."
    },
    "permeability_relative": {
      "type": "number",
      "description": "Relative permeability \u03bcr (copper/aluminium = 1.0, steel \u2248 1000).  Default 1.0."
    },
    "aperture_length_m": {
      "type": "number",
      "description": "Longest dimension of the largest aperture/slot [m].  Set to 0 or omit for a sealed enclosure (default 0)."
    }
  },
  "required": [
    "freq_hz",
    "thickness_m"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
