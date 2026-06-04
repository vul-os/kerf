# sensorcond

*Module: `kerf_electronics.sensorcond.tools` · Domain: electronics*

This module registers **15** LLM tool(s):

- [`sensorcond_bridge_output`](#sensorcond-bridge-output)
- [`sensorcond_bridge_excitation`](#sensorcond-bridge-excitation)
- [`sensorcond_strain_to_stress`](#sensorcond-strain-to-stress)
- [`sensorcond_rtd_resistance`](#sensorcond-rtd-resistance)
- [`sensorcond_rtd_temperature`](#sensorcond-rtd-temperature)
- [`sensorcond_rtd_lead_wire`](#sensorcond-rtd-lead-wire)
- [`sensorcond_thermocouple`](#sensorcond-thermocouple)
- [`sensorcond_ina_gain`](#sensorcond-ina-gain)
- [`sensorcond_adc_bits`](#sensorcond-adc-bits)
- [`sensorcond_enob`](#sensorcond-enob)
- [`sensorcond_antialias_corner`](#sensorcond-antialias-corner)
- [`sensorcond_4_20ma_scale`](#sensorcond-4-20ma-scale)
- [`sensorcond_burden_voltage`](#sensorcond-burden-voltage)
- [`sensorcond_noise_rss`](#sensorcond-noise-rss)
- [`sensorcond_filter_topology`](#sensorcond-filter-topology)

---

## `sensorcond_bridge_output`

Compute Wheatstone bridge output voltage for a strain-gauge circuit.

Supports quarter-bridge (one active arm), half-bridge (two complementary arms, e.g. bending beam), and full-bridge (four active arms).

Returns both linearised and exact (nonlinear) output voltages, plus the nonlinearity error percentage and lead-wire sensitivity loss.

A warning is issued when ΔR/R > 1% (nonlinearity significant for quarter/half bridges).

Input: { excitation_v, gauge_factor, strain_ue, config?, lead_resistance_ohm?, nominal_resistance_ohm? }
Returns: { ok, config, vout_linearised_v, vout_exact_v, nonlinearity_error_pct, lead_wire_sensitivity_loss_pct, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "excitation_v": {
      "type": "number",
      "description": "Bridge excitation voltage [V]."
    },
    "gauge_factor": {
      "type": "number",
      "description": "Strain-gauge gauge factor (dimensionless, typical 2.0)."
    },
    "strain_ue": {
      "type": "number",
      "description": "Applied strain [\u00b5\u03b5 = microstrain]."
    },
    "config": {
      "type": "string",
      "enum": [
        "quarter",
        "half",
        "full"
      ],
      "description": "Bridge configuration: 'quarter', 'half', or 'full' (default 'quarter')."
    },
    "lead_resistance_ohm": {
      "type": "number",
      "description": "Total lead resistance for the active arm [\u03a9] (default 0)."
    },
    "nominal_resistance_ohm": {
      "type": "number",
      "description": "Nominal gauge resistance Rg [\u03a9] (default 350)."
    }
  },
  "required": [
    "excitation_v",
    "gauge_factor",
    "strain_ue"
  ]
}
```

---

## `sensorcond_bridge_excitation`

Compute bridge excitation power per arm, total power, and maximum safe excitation voltage for bonded strain gauges.

For a balanced bridge (all arms = Rg):
  P_arm = Vex² / (4 × Rg)
  P_total = Vex² / Rg
  Vex_max = sqrt(4 × Rg × 30 mW)   [typical 30 mW self-heating limit]

A warning is issued when P_arm exceeds 30 mW.

Input: { excitation_v, nominal_resistance_ohm? }
Returns: { ok, i_arm_a, p_arm_w, p_total_w, max_safe_excitation_v }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "excitation_v": {
      "type": "number",
      "description": "Bridge excitation voltage [V]."
    },
    "nominal_resistance_ohm": {
      "type": "number",
      "description": "Nominal gauge resistance Rg [\u03a9] (default 350)."
    }
  },
  "required": [
    "excitation_v"
  ]
}
```

---

## `sensorcond_strain_to_stress`

Convert strain-gauge microstrain [µε] to stress [MPa] using Hooke's law.

  σ = E × ε

Common Young's moduli: steel ≈ 200 GPa, aluminium ≈ 70 GPa, titanium ≈ 114 GPa, copper ≈ 128 GPa.

Input: { strain_ue, youngs_modulus_gpa }
Returns: { ok, stress_pa, stress_mpa }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "strain_ue": {
      "type": "number",
      "description": "Strain [\u00b5\u03b5 = microstrain]."
    },
    "youngs_modulus_gpa": {
      "type": "number",
      "description": "Young's modulus [GPa]."
    }
  },
  "required": [
    "strain_ue",
    "youngs_modulus_gpa"
  ]
}
```

---

## `sensorcond_rtd_resistance`

Callendar-Van Dusen forward model: RTD temperature → resistance.

IEC 60751:2008:
  T ≥ 0 °C: R(T) = R₀ × (1 + A×T + B×T²)
  T < 0 °C: R(T) = R₀ × (1 + A×T + B×T² + C×(T−100)×T³)

Default coefficients for platinum PT100 (IEC 60751):
  A = 3.9083e-3 °C⁻¹, B = −5.775e-7 °C⁻², C = −4.183e-12 °C⁻⁴

Valid range: −200 °C to +850 °C.  A warning is issued outside this range.

Input: { temperature_c, r0_ohm? }
Returns: { ok, temperature_c, resistance_ohm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "temperature_c": {
      "type": "number",
      "description": "Temperature [\u00b0C]."
    },
    "r0_ohm": {
      "type": "number",
      "description": "RTD resistance at 0 \u00b0C [\u03a9] (default 100.0 for PT100)."
    }
  },
  "required": [
    "temperature_c"
  ]
}
```

---

## `sensorcond_rtd_temperature`

Callendar-Van Dusen inverse model: RTD resistance → temperature.

For T ≥ 0 °C: closed-form quadratic solution.
For T < 0 °C: Newton-Raphson iteration with cubic C term.

Default coefficients: IEC 60751 PT100 (R₀ = 100 Ω, A = 3.9083e-3).

Input: { resistance_ohm, r0_ohm? }
Returns: { ok, resistance_ohm, r0_ohm, temperature_c }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "resistance_ohm": {
      "type": "number",
      "description": "Measured RTD resistance [\u03a9]."
    },
    "r0_ohm": {
      "type": "number",
      "description": "RTD resistance at 0 \u00b0C [\u03a9] (default 100.0 for PT100)."
    }
  },
  "required": [
    "resistance_ohm"
  ]
}
```

---

## `sensorcond_rtd_lead_wire`

Compute RTD lead-wire resistance error and corrected resistance.

2-wire: both leads add to measurement (R_error = 2 × R_lead).
3-wire: Kelvin connection cancels lead resistance (ideal: R_error ≈ 0).
4-wire: zero lead resistance error.

Temperature error estimate: ΔT ≈ R_error / (R₀ × α)  where α ≈ 3.85e-3 °C⁻¹.

A warning is issued for 2-wire errors > 0.5 °C.

Input: { measurement_resistance_ohm, lead_resistance_ohm, wiring?, r0_ohm? }
Returns: { ok, r_error_ohm, temperature_error_c, corrected_resistance_ohm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "measurement_resistance_ohm": {
      "type": "number",
      "description": "Raw measured resistance [\u03a9]."
    },
    "lead_resistance_ohm": {
      "type": "number",
      "description": "Resistance of one lead wire [\u03a9]."
    },
    "wiring": {
      "type": "string",
      "enum": [
        "2-wire",
        "3-wire",
        "4-wire"
      ],
      "description": "RTD wiring configuration (default '3-wire')."
    },
    "r0_ohm": {
      "type": "number",
      "description": "RTD resistance at 0 \u00b0C [\u03a9] (default 100.0)."
    }
  },
  "required": [
    "measurement_resistance_ohm",
    "lead_resistance_ohm"
  ]
}
```

---

## `sensorcond_thermocouple`

Convert thermocouple EMF [mV] to temperature [°C] using the NIST ITS-90 inverse polynomial, with cold-junction compensation.

Supported types: J, K, T, E, N, S, R, B.

Cold-junction compensation is applied using a linear Seebeck coefficient approximation around 0 °C.  A warning is issued when the cold-junction temperature exceeds ±5 °C (linear CJC may introduce ~0.5 °C error).

Input: { voltage_mv, tc_type, cold_junction_temp_c? }
Returns: { ok, tc_type, temperature_c, cjc_voltage_mv, effective_voltage_mv }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "voltage_mv": {
      "type": "number",
      "description": "Measured thermocouple EMF [mV]."
    },
    "tc_type": {
      "type": "string",
      "enum": [
        "J",
        "K",
        "T",
        "E",
        "N",
        "S",
        "R",
        "B"
      ],
      "description": "Thermocouple type."
    },
    "cold_junction_temp_c": {
      "type": "number",
      "description": "Cold-junction (reference) temperature [\u00b0C] (default 0)."
    }
  },
  "required": [
    "voltage_mv",
    "tc_type"
  ]
}
```

---

## `sensorcond_ina_gain`

Compute instrumentation amplifier gain and total input-referred error.

Three-op-amp INA:  G = 1 + 2 × R_internal / R_gain

Error sources (all input-referred):
  e_offset  = V_os [µV]
  e_cmrr    = V_cm / CMRR [µV]
  e_drift   = V_os × G × gain_drift_ppm_c × ΔT [µV]
  e_total   = RSS(e_offset, e_cmrr, e_drift)

CMRR-limited warning issued when e_cmrr > e_offset.

Input: { r_gain_ohm, r_internal_ohm?, gain_error_pct?, offset_voltage_uv?, cmrr_db?, common_mode_v?, gain_drift_ppm_c?, temperature_delta_c? }
Returns: { ok, gain, e_offset_uv, e_cmrr_uv, e_total_rms_uv, cmrr_limited }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_gain_ohm": {
      "type": "number",
      "description": "External gain-setting resistor [\u03a9]."
    },
    "r_internal_ohm": {
      "type": "number",
      "description": "Internal resistor pair [\u03a9] (default 49.4 k\u03a9 for INA128)."
    },
    "gain_error_pct": {
      "type": "number",
      "description": "Initial gain error [%] (default 0.5%)."
    },
    "offset_voltage_uv": {
      "type": "number",
      "description": "Input offset voltage [\u00b5V] (default 50 \u00b5V)."
    },
    "cmrr_db": {
      "type": "number",
      "description": "CMRR [dB] (default 80 dB)."
    },
    "common_mode_v": {
      "type": "number",
      "description": "Common-mode voltage at inputs [V] (default 0)."
    },
    "gain_drift_ppm_c": {
      "type": "number",
      "description": "Gain temperature coefficient [ppm/\u00b0C] (default 10)."
    },
    "temperature_delta_c": {
      "type": "number",
      "description": "Temperature change from calibration [\u00b0C] (default 25)."
    }
  },
  "required": [
    "r_gain_ohm"
  ]
}
```

---

## `sensorcond_adc_bits`

Compute the minimum ADC bit-width for a target measurement resolution.

  N_bits ≥ ceil(log2(FSR / target_resolution))

A warning is issued when ≥ 24 bits are required (design is typically noise-limited before bitwidth-limited).

Input: { full_scale_range_v, target_resolution_mv }
Returns: { ok, ideal_bits, recommended_bits, lsb_size_mv }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "full_scale_range_v": {
      "type": "number",
      "description": "ADC full-scale input range [V]."
    },
    "target_resolution_mv": {
      "type": "number",
      "description": "Required measurement resolution [mV]."
    }
  },
  "required": [
    "full_scale_range_v",
    "target_resolution_mv"
  ]
}
```

---

## `sensorcond_enob`

Compute Effective Number of Bits (ENOB) from input-referred RMS noise.

  ENOB = log2(FSR / (V_noise_rms × √12))

Warnings are issued when ENOB < 10 (noise-limited) or > 24 (suspect inputs).

Input: { noise_rms_uv, full_scale_range_v }
Returns: { ok, enob }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "noise_rms_uv": {
      "type": "number",
      "description": "Input-referred RMS noise [\u00b5V]."
    },
    "full_scale_range_v": {
      "type": "number",
      "description": "ADC full-scale input range [V]."
    }
  },
  "required": [
    "noise_rms_uv",
    "full_scale_range_v"
  ]
}
```

---

## `sensorcond_antialias_corner`

Recommend the anti-alias filter −3 dB corner frequency for an ADC.

Uses Butterworth roll-off approximation:
  fc = f_nyq / 10^(A_stop / (20 × N))

A warning is issued when fc < fs/4 (filter is cutting into the usable band).

Input: { sample_rate_hz, stopband_attenuation_db?, filter_order? }
Returns: { ok, nyquist_hz, filter_corner_hz, bandwidth_ratio }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sample_rate_hz": {
      "type": "number",
      "description": "ADC sample rate [Hz]."
    },
    "stopband_attenuation_db": {
      "type": "number",
      "description": "Required attenuation at Nyquist [dB] (default 40 dB)."
    },
    "filter_order": {
      "type": "integer",
      "description": "Filter order N (default 2)."
    }
  },
  "required": [
    "sample_rate_hz"
  ]
}
```

---

## `sensorcond_4_20ma_scale`

Scale a 4-20 mA loop current to engineering units.

  value = span_low + (I − 4) / 16 × (span_high − span_low)

A warning is issued when current is outside [3.8, 20.5] mA (indicates open-circuit or over-range fault).

Input: { current_ma, span_low, span_high }
Returns: { ok, fraction, value }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "current_ma": {
      "type": "number",
      "description": "Loop current [mA]."
    },
    "span_low": {
      "type": "number",
      "description": "Engineering-unit value at 4 mA."
    },
    "span_high": {
      "type": "number",
      "description": "Engineering-unit value at 20 mA."
    }
  },
  "required": [
    "current_ma",
    "span_low",
    "span_high"
  ]
}
```

---

## `sensorcond_burden_voltage`

Compute 4-20 mA loop burden voltage and compliance headroom.

  V_burden = I × R_burden
  V_available = V_supply − V_burden
  compliance_margin = V_available − V_min_transmitter

A warning is issued when compliance margin < 1 V.

Input: { current_ma, burden_resistance_ohm, supply_voltage_v, transmitter_min_compliance_v? }
Returns: { ok, v_burden_v, v_available_v, compliance_margin_v, compliant }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "current_ma": {
      "type": "number",
      "description": "Loop current [mA]."
    },
    "burden_resistance_ohm": {
      "type": "number",
      "description": "Total series burden resistance [\u03a9]."
    },
    "supply_voltage_v": {
      "type": "number",
      "description": "Loop supply voltage [V]."
    },
    "transmitter_min_compliance_v": {
      "type": "number",
      "description": "Minimum transmitter compliance voltage [V] (default 3 V)."
    }
  },
  "required": [
    "current_ma",
    "burden_resistance_ohm",
    "supply_voltage_v"
  ]
}
```

---

## `sensorcond_noise_rss`

Compute root-sum-of-squares (RSS) noise budget from a list of independent noise sources.

  V_total_rms = sqrt(V₁² + V₂² + ... + Vₙ²)

A warning is issued when any single source dominates > 70% of the variance.

Input: { noise_sources_uv: [n1, n2, ...] }
Returns: { ok, total_rms_uv, dominant_source_index, dominant_source_fraction }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "noise_sources_uv": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "List of RMS noise amplitudes [\u00b5V] from independent sources."
    }
  },
  "required": [
    "noise_sources_uv"
  ]
}
```

---

## `sensorcond_filter_topology`

Recommend Sallen-Key (SK) or Multiple-Feedback (MFB) topology for a second-order active lowpass anti-alias filter.

Rules (Horowitz & Hill §6.3 / TI SLOA049):
  Sallen-Key preferred: G ≤ 3, Q ≤ 1, single-ended supply, non-inverting.
  MFB preferred: G > 3, Q > 1, low-noise priority with high Q.

Input: { gain, q_factor, supply_single_ended?, low_noise_priority? }
Returns: { ok, recommended_topology, reasons, sk_score, mfb_score }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "gain": {
      "type": "number",
      "description": "Required filter gain (absolute, \u2265 1)."
    },
    "q_factor": {
      "type": "number",
      "description": "Required Q factor (0.707 \u2192 Butterworth 2nd-order, 0.577 \u2192 Bessel, 1.0 \u2192 Chebyshev 3 dB)."
    },
    "supply_single_ended": {
      "type": "boolean",
      "description": "True if only a single-ended supply is available (default False)."
    },
    "low_noise_priority": {
      "type": "boolean",
      "description": "True if minimising noise is the primary design concern (default False)."
    }
  },
  "required": [
    "gain",
    "q_factor"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
