# rfmatch

*Module: `kerf_electronics.rfmatch.tools` · Domain: electronics*

This module registers **8** LLM tool(s):

- [`rfmatch_reflection`](#rfmatch-reflection)
- [`rfmatch_lsection`](#rfmatch-lsection)
- [`rfmatch_pi`](#rfmatch-pi)
- [`rfmatch_t`](#rfmatch-t)
- [`rfmatch_quarter_wave`](#rfmatch-quarter-wave)
- [`rfmatch_single_stub`](#rfmatch-single-stub)
- [`rfmatch_microstrip_synth`](#rfmatch-microstrip-synth)
- [`rfmatch_microstrip_anal`](#rfmatch-microstrip-anal)

---

## `rfmatch_reflection`

Compute the complex reflection coefficient Γ = (Z_L − Z0) / (Z_L + Z0) for a load impedance Z_L relative to a reference impedance Z0.

Also returns |Γ|, ∠Γ [degrees], VSWR, return loss [dB], and mismatch loss [dB].

Input: { z_load_re, z_load_im?, z0? }
Returns: { ok, gamma_re, gamma_im, gamma_mag, gamma_phase_deg, vswr, return_loss_db, mismatch_loss_db }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z_load_re": {
      "type": "number",
      "description": "Real part of the load impedance [\u03a9]."
    },
    "z_load_im": {
      "type": "number",
      "description": "Imaginary part of the load impedance [\u03a9] (default 0)."
    },
    "z0": {
      "type": "number",
      "description": "Reference impedance [\u03a9] (default 50 \u03a9)."
    }
  },
  "required": [
    "z_load_re"
  ]
}
```

---

## `rfmatch_lsection`

Synthesise an L-section impedance-matching network for complex source and load impedances at a given frequency.

Returns both canonical L-section topologies (shunt-source/series-load and series-source/shunt-load) with component L/C values and loaded-Q.
Non-realizable or negative-component solutions are flagged in the 'warnings' field; the function never raises.

Input: { z_source_re, z_source_im?, z_load_re, z_load_im?, freq_hz }
Returns: { ok, Q, solutions: [ { topology, component_type_shunt, component_value_shunt, component_type_series, component_value_series, realizable, warnings }, ... ] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z_source_re": {
      "type": "number",
      "description": "Real part of source impedance [\u03a9]."
    },
    "z_source_im": {
      "type": "number",
      "description": "Imaginary part of source impedance [\u03a9] (default 0)."
    },
    "z_load_re": {
      "type": "number",
      "description": "Real part of load impedance [\u03a9]."
    },
    "z_load_im": {
      "type": "number",
      "description": "Imaginary part of load impedance [\u03a9] (default 0)."
    },
    "freq_hz": {
      "type": "number",
      "description": "Operating frequency [Hz]."
    }
  },
  "required": [
    "z_source_re",
    "z_load_re",
    "freq_hz"
  ]
}
```

---

## `rfmatch_pi`

Synthesise a Pi (π) impedance-matching network for a target loaded-Q.

A Pi-network provides bandwidth control via the loaded-Q and can match a wider impedance ratio than a simple L-section.  The loaded-Q must exceed Q_min = sqrt(R_high/R_low − 1).

Input: { r_source, r_load, freq_hz, q_loaded }
Returns: { ok, r_virtual, X_p1_ohm, X_series_ohm, X_p2_ohm, component_type_p1/series/p2, component_value_p1/series/p2, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_source": {
      "type": "number",
      "description": "Source resistance [\u03a9]."
    },
    "r_load": {
      "type": "number",
      "description": "Load resistance [\u03a9]."
    },
    "freq_hz": {
      "type": "number",
      "description": "Operating frequency [Hz]."
    },
    "q_loaded": {
      "type": "number",
      "description": "Target loaded-Q (must be > sqrt(R_high/R_low \u2212 1))."
    }
  },
  "required": [
    "r_source",
    "r_load",
    "freq_hz",
    "q_loaded"
  ]
}
```

---

## `rfmatch_t`

Synthesise a T-network impedance-matching network for a target loaded-Q.

A T-network is the dual of a Pi-network: two series arms and one shunt arm.  The loaded-Q must exceed Q_min = sqrt(R_high/R_low − 1).

Input: { r_source, r_load, freq_hz, q_loaded }
Returns: { ok, r_virtual, X_s1_ohm, X_p_ohm, X_s2_ohm, component_type_s1/p/s2, component_value_s1/p/s2, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_source": {
      "type": "number",
      "description": "Source resistance [\u03a9]."
    },
    "r_load": {
      "type": "number",
      "description": "Load resistance [\u03a9]."
    },
    "freq_hz": {
      "type": "number",
      "description": "Operating frequency [Hz]."
    },
    "q_loaded": {
      "type": "number",
      "description": "Target loaded-Q (must be > sqrt(R_high/R_low \u2212 1))."
    }
  },
  "required": [
    "r_source",
    "r_load",
    "freq_hz",
    "q_loaded"
  ]
}
```

---

## `rfmatch_quarter_wave`

Compute the characteristic impedance Z0 of a quarter-wave transformer that matches a source resistance R_source to a load resistance R_load.

Formula: Z0 = sqrt(R_source × R_load)

Valid for resistive (real) source and load only.  At the design frequency the transformer is exactly λ/4 long (90° electrical length).

Input: { r_source, r_load }
Returns: { ok, z0_transformer_ohm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_source": {
      "type": "number",
      "description": "Source resistance [\u03a9]."
    },
    "r_load": {
      "type": "number",
      "description": "Load resistance [\u03a9]."
    }
  },
  "required": [
    "r_source",
    "r_load"
  ]
}
```

---

## `rfmatch_single_stub`

Single-stub impedance matching: compute the feed-line distance to stub and stub electrical length for a given load impedance.

Uses the classical single-stub matching method (Pozar §5.2).  Returns two solutions (if they exist); each solution includes the feed-line length d and stub length l as fractions of wavelength and in degrees.

Input: { z_load_re, z_load_im?, z0?, stub_type?, termination? }
Returns: { ok, solutions: [ { d_wavelength, d_degrees, stub_length_wavelength, stub_length_degrees, realizable, notes }, ... ] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z_load_re": {
      "type": "number",
      "description": "Real part of load impedance [\u03a9]."
    },
    "z_load_im": {
      "type": "number",
      "description": "Imaginary part of load impedance [\u03a9] (default 0)."
    },
    "z0": {
      "type": "number",
      "description": "System characteristic impedance [\u03a9] (default 50 \u03a9)."
    },
    "stub_type": {
      "type": "string",
      "enum": [
        "shunt",
        "series"
      ],
      "description": "'shunt' (default) or 'series'."
    },
    "termination": {
      "type": "string",
      "enum": [
        "short",
        "open"
      ],
      "description": "'short' (default) or 'open' stub termination."
    }
  },
  "required": [
    "z_load_re"
  ]
}
```

---

## `rfmatch_microstrip_synth`

Microstrip trace width synthesis using the Hammerstad & Jensen (1980) closed-form equations (Pozar §3.8).

Given a target characteristic impedance Z0 and substrate parameters, computes the trace width W/H ratio, effective permittivity εr_eff, and a self-check impedance.

Input: { z0_target, er, h?, t? }
Returns: { ok, width, width_to_height, er_eff, z0_achieved, error_percent, regime, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z0_target": {
      "type": "number",
      "description": "Target characteristic impedance [\u03a9]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity \u03b5r."
    },
    "h": {
      "type": "number",
      "description": "Substrate height (any consistent unit; default 1.0 \u2192 result W in same unit)."
    },
    "t": {
      "type": "number",
      "description": "Trace thickness in same unit as h (0 = ideal thin trace; default 0)."
    }
  },
  "required": [
    "z0_target",
    "er"
  ]
}
```

---

## `rfmatch_microstrip_anal`

Microstrip analysis: compute characteristic impedance Z0 and effective permittivity εr_eff from physical dimensions (Hammerstad & Jensen).

Input: { width, h, er, t? }
Returns: { ok, width_to_height, er_eff, z0, wavelength_factor }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "width": {
      "type": "number",
      "description": "Trace width [same unit as h]."
    },
    "h": {
      "type": "number",
      "description": "Substrate height [same unit as width]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity \u03b5r."
    },
    "t": {
      "type": "number",
      "description": "Trace thickness (0 = ideal thin trace; default 0)."
    }
  },
  "required": [
    "width",
    "h",
    "er"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
