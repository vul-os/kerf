# afilter

*Module: `kerf_electronics.afilter.tools` · Domain: electronics*

This module registers **14** LLM tool(s):

- [`afilter_butterworth_order`](#afilter-butterworth-order)
- [`afilter_chebyshev_order`](#afilter-chebyshev-order)
- [`afilter_bessel_order`](#afilter-bessel-order)
- [`afilter_butterworth_poles`](#afilter-butterworth-poles)
- [`afilter_chebyshev_poles`](#afilter-chebyshev-poles)
- [`afilter_bessel_poles`](#afilter-bessel-poles)
- [`afilter_butterworth_g`](#afilter-butterworth-g)
- [`afilter_chebyshev_g`](#afilter-chebyshev-g)
- [`afilter_lp_to_lp`](#afilter-lp-to-lp)
- [`afilter_lp_to_hp`](#afilter-lp-to-hp)
- [`afilter_lp_to_bp`](#afilter-lp-to-bp)
- [`afilter_sallen_key`](#afilter-sallen-key)
- [`afilter_mfb`](#afilter-mfb)
- [`afilter_response`](#afilter-response)

---

## `afilter_butterworth_order`

Compute the minimum Butterworth lowpass filter order that meets a passband ripple and stopband attenuation specification.

Formula: n ≥ log(ε_s²/ε_p²) / (2 log(Ωs/Ωp))

Input: { passband_freq_hz, stopband_freq_hz, passband_ripple_db, stopband_atten_db }
Returns: { ok, order, n_exact, fc_hz, omega_c_rads }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "passband_freq_hz": {
      "type": "number",
      "description": "Passband cutoff (\u22123 dB) frequency [Hz]."
    },
    "stopband_freq_hz": {
      "type": "number",
      "description": "Stopband edge frequency [Hz] (must be > passband_freq_hz)."
    },
    "passband_ripple_db": {
      "type": "number",
      "description": "Maximum in-band ripple [dB] (use 3.0 for Butterworth \u22123 dB)."
    },
    "stopband_atten_db": {
      "type": "number",
      "description": "Minimum stopband attenuation [dB] (e.g. 40)."
    }
  },
  "required": [
    "passband_freq_hz",
    "stopband_freq_hz",
    "passband_ripple_db",
    "stopband_atten_db"
  ]
}
```

---

## `afilter_chebyshev_order`

Compute the minimum Chebyshev-I lowpass filter order from passband ripple and stopband attenuation specifications.

Formula: n ≥ acosh(sqrt(ε_s²/ε_p²)) / acosh(Ωs/Ωp)

Input: { passband_freq_hz, stopband_freq_hz, passband_ripple_db, stopband_atten_db }
Returns: { ok, order, n_exact, epsilon }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "passband_freq_hz": {
      "type": "number",
      "description": "Passband edge frequency [Hz]."
    },
    "stopband_freq_hz": {
      "type": "number",
      "description": "Stopband edge frequency [Hz]."
    },
    "passband_ripple_db": {
      "type": "number",
      "description": "Passband ripple [dB]."
    },
    "stopband_atten_db": {
      "type": "number",
      "description": "Minimum stopband attenuation [dB]."
    }
  },
  "required": [
    "passband_freq_hz",
    "stopband_freq_hz",
    "passband_ripple_db",
    "stopband_atten_db"
  ]
}
```

---

## `afilter_bessel_order`

Estimate the minimum Bessel/Thomson filter order for a target group-delay flatness over a normalised bandwidth ratio.

Bessel filters are maximally flat in group delay.  This tool estimates the order required so that group delay stays within ±(flatness/2)% of the DC value up to bandwidth_ratio × ω_n.

Input: { group_delay_flatness_percent, bandwidth_ratio }
Returns: { ok, order, group_delay_flatness_percent, bandwidth_ratio }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "group_delay_flatness_percent": {
      "type": "number",
      "description": "Maximum allowed group-delay deviation [%] (e.g. 5.0)."
    },
    "bandwidth_ratio": {
      "type": "number",
      "description": "Ratio of flat-delay bandwidth to normalised cutoff (> 1)."
    }
  },
  "required": [
    "group_delay_flatness_percent",
    "bandwidth_ratio"
  ]
}
```

---

## `afilter_butterworth_poles`

Return the normalised LP prototype pole locations for a Butterworth filter of order n (unit cutoff ω_c = 1 rad/s, left half-plane).

All n poles lie on the unit circle.

Input: { order }
Returns: { ok, order, poles: [{re, im}, ...] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "order": {
      "type": "integer",
      "description": "Filter order (1 \u2264 n \u2264 20).",
      "minimum": 1,
      "maximum": 20
    }
  },
  "required": [
    "order"
  ]
}
```

---

## `afilter_chebyshev_poles`

Return normalised LP prototype pole locations for a Chebyshev-I filter (passband edge at ω = 1 rad/s).  Poles lie on an ellipse in the LHP.

Input: { order, passband_ripple_db }
Returns: { ok, order, passband_ripple_db, epsilon, alpha, poles: [{re, im}] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "order": {
      "type": "integer",
      "description": "Filter order.",
      "minimum": 1,
      "maximum": 20
    },
    "passband_ripple_db": {
      "type": "number",
      "description": "Passband ripple [dB]."
    }
  },
  "required": [
    "order",
    "passband_ripple_db"
  ]
}
```

---

## `afilter_bessel_poles`

Return normalised LP prototype pole locations for a Bessel/Thomson filter (group delay normalised to 1 s at DC).  Poles are roots of the reverse Bessel polynomial computed via Durand-Kerner iteration.

Supports order 1–10.

Input: { order }
Returns: { ok, order, poles: [{re, im}] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "order": {
      "type": "integer",
      "description": "Filter order (1 \u2264 n \u2264 10).",
      "minimum": 1,
      "maximum": 10
    }
  },
  "required": [
    "order"
  ]
}
```

---

## `afilter_butterworth_g`

Return doubly-terminated Butterworth ladder g-values for a normalised LP prototype (g_0 = 1, ω_c = 1 rad/s).

g_k = 2 sin((2k−1)π/(2n))  for k=1…n;  g_{n+1} = 1.

Input: { order }
Returns: { ok, order, g_values (n+2 element list) }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "order": {
      "type": "integer",
      "description": "Filter order (1 \u2264 n \u2264 20).",
      "minimum": 1,
      "maximum": 20
    }
  },
  "required": [
    "order"
  ]
}
```

---

## `afilter_chebyshev_g`

Return doubly-terminated Chebyshev-I ladder g-values for a normalised LP prototype (g_0 = 1, passband edge ω_c = 1 rad/s).

Input: { order, passband_ripple_db }
Returns: { ok, order, passband_ripple_db, g_values (n+2 element list) }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "order": {
      "type": "integer",
      "description": "Filter order (1 \u2264 n \u2264 20).",
      "minimum": 1,
      "maximum": 20
    },
    "passband_ripple_db": {
      "type": "number",
      "description": "Passband ripple [dB]."
    }
  },
  "required": [
    "order",
    "passband_ripple_db"
  ]
}
```

---

## `afilter_lp_to_lp`

Frequency and impedance denormalise a normalised LP ladder prototype to an LP RLC filter at a target cutoff frequency and impedance.

Series elements → inductors (L = g_k × Z0 / ω_c).
Shunt elements → capacitors (C = g_k / (Z0 × ω_c)).

Input: { g_values, cutoff_freq_hz, impedance_ohm? }
Returns: { ok, r_source, r_load, elements: [{index, type, value}], warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "g_values": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Ladder g-values (n+2 elements: g_0\u2026g_{n+1})."
    },
    "cutoff_freq_hz": {
      "type": "number",
      "description": "Target \u22123 dB cutoff frequency [Hz]."
    },
    "impedance_ohm": {
      "type": "number",
      "description": "Reference impedance [\u03a9] (default 50 \u03a9)."
    }
  },
  "required": [
    "g_values",
    "cutoff_freq_hz"
  ]
}
```

---

## `afilter_lp_to_hp`

LP prototype → HP RLC filter via the s → ω_c/s frequency inversion.

LP series L → HP shunt C = 1/(g_k × Z0 × ω_c).
LP shunt C → HP series L = Z0 / (g_k × ω_c).

Input: { g_values, cutoff_freq_hz, impedance_ohm? }
Returns: { ok, r_source, r_load, elements: [{index, type, value}], warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "g_values": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Ladder g-values."
    },
    "cutoff_freq_hz": {
      "type": "number",
      "description": "HP cutoff frequency [Hz]."
    },
    "impedance_ohm": {
      "type": "number",
      "description": "Reference impedance [\u03a9] (default 50 \u03a9)."
    }
  },
  "required": [
    "g_values",
    "cutoff_freq_hz"
  ]
}
```

---

## `afilter_lp_to_bp`

LP prototype → BP RLC filter via the LP→BP transformation s → Q(s/ω_0 + ω_0/s), where Q = ω_0/BW.

Each prototype element maps to an LC resonant pair centred at ω_0.

Input: { g_values, center_freq_hz, bandwidth_hz, impedance_ohm? }
Returns: { ok, Q, elements: [{index, type, resonator: {L_h, C_f, f0_hz}}], warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "g_values": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Ladder g-values."
    },
    "center_freq_hz": {
      "type": "number",
      "description": "BP center frequency [Hz]."
    },
    "bandwidth_hz": {
      "type": "number",
      "description": "BP 3dB bandwidth [Hz]."
    },
    "impedance_ohm": {
      "type": "number",
      "description": "Reference impedance [\u03a9] (default 50 \u03a9)."
    }
  },
  "required": [
    "g_values",
    "center_freq_hz",
    "bandwidth_hz"
  ]
}
```

---

## `afilter_sallen_key`

Sallen-Key equal-component second-order lowpass op-amp filter design.

Equal capacitors C1=C2=C, equal resistors R1=R2=R=1/(ω_n×C).
Required gain K = 3 − 1/Q.  Non-realizable if Q < 0.5 or Q → ∞.

Input: { cutoff_freq_hz, Q, gain?, capacitor_f? }
Returns: { ok, C1_f, C2_f, R1_ohm, R2_ohm, Rf_ohm, Rg_ohm, K_required_for_Q, realizable, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "cutoff_freq_hz": {
      "type": "number",
      "description": "Pole frequency (natural frequency) [Hz]."
    },
    "Q": {
      "type": "number",
      "description": "Pole Q factor (\u2265 0.5 for real equal-component design)."
    },
    "gain": {
      "type": "number",
      "description": "DC gain K (default 1.0 for unity gain)."
    },
    "capacitor_f": {
      "type": "number",
      "description": "Capacitor value [F] (default 10 nF)."
    }
  },
  "required": [
    "cutoff_freq_hz",
    "Q"
  ]
}
```

---

## `afilter_mfb`

Multiple-Feedback (MFB/Rauch) second-order inverting lowpass op-amp filter component selection.

Equal capacitors C1=C2=C.  Realizable when discriminant ≥ 0: (ω_n/Q)² ≥ 4ω_n²(1+|K|).  Non-realizable cases return ok=True with realizable=False.

Input: { cutoff_freq_hz, Q, gain?, capacitor_f? }
Returns: { ok, C1_f, C2_f, R1_ohm, R2_ohm, R3_ohm, realizable, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "cutoff_freq_hz": {
      "type": "number",
      "description": "Pole frequency [Hz]."
    },
    "Q": {
      "type": "number",
      "description": "Pole Q factor."
    },
    "gain": {
      "type": "number",
      "description": "Midband gain (negative; default \u22121.0)."
    },
    "capacitor_f": {
      "type": "number",
      "description": "Capacitor value [F] (default 10 nF)."
    }
  },
  "required": [
    "cutoff_freq_hz",
    "Q"
  ]
}
```

---

## `afilter_response`

Compute magnitude (dB), phase (degrees), and group delay (s) of a filter defined by its poles and zeros at a given frequency.

Poles and zeros are specified as {re, im} objects.
Group delay is approximated by central difference of phase.

Input: { poles, zeros?, gain_dc?, freq_hz }
Returns: { ok, freq_hz, magnitude_db, phase_deg, group_delay_s, H_re, H_im, H_mag }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "poles": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "re": {
            "type": "number"
          },
          "im": {
            "type": "number"
          }
        },
        "required": [
          "re",
          "im"
        ]
      },
      "description": "Pole locations as [{re, im}] objects."
    },
    "zeros": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "re": {
            "type": "number"
          },
          "im": {
            "type": "number"
          }
        },
        "required": [
          "re",
          "im"
        ]
      },
      "description": "Zero locations as [{re, im}] objects (default empty)."
    },
    "gain_dc": {
      "type": "number",
      "description": "DC gain (default 1.0)."
    },
    "freq_hz": {
      "type": "number",
      "description": "Evaluation frequency [Hz]."
    }
  },
  "required": [
    "poles",
    "freq_hz"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
