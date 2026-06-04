# dsp

*Module: `kerf_electronics.dsp.tools` · Domain: electronics*

This module registers **19** LLM tool(s):

- [`dsp_fft`](#dsp-fft)
- [`dsp_ifft`](#dsp-ifft)
- [`dsp_spectrum`](#dsp-spectrum)
- [`dsp_bin_frequency`](#dsp-bin-frequency)
- [`dsp_fir_lp`](#dsp-fir-lp)
- [`dsp_fir_hp`](#dsp-fir-hp)
- [`dsp_fir_bp`](#dsp-fir-bp)
- [`dsp_fir_order`](#dsp-fir-order)
- [`dsp_iir_butterworth_lp`](#dsp-iir-butterworth-lp)
- [`dsp_iir_butterworth_hp`](#dsp-iir-butterworth-hp)
- [`dsp_biquad_lp`](#dsp-biquad-lp)
- [`dsp_biquad_hp`](#dsp-biquad-hp)
- [`dsp_biquad_bp`](#dsp-biquad-bp)
- [`dsp_biquad_notch`](#dsp-biquad-notch)
- [`dsp_biquad_peaking`](#dsp-biquad-peaking)
- [`dsp_freq_response`](#dsp-freq-response)
- [`dsp_group_delay`](#dsp-group-delay)
- [`dsp_nyquist_check`](#dsp-nyquist-check)
- [`dsp_adc_snr`](#dsp-adc-snr)

---

## `dsp_fft`

Compute the radix-2 Cooley-Tukey FFT of a real or complex sequence.

Input length must be a power of 2.  Use dsp_spectrum for the full one-sided magnitude/phase spectrum of a real signal.

Input: { x: [{re, im} | number, ...] }
Returns: { ok, N, X: [{re, im}, ...] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "x": {
      "type": "array",
      "items": {},
      "description": "Input samples: either plain numbers (real) or {re, im} objects. Length must be a power of 2."
    }
  },
  "required": [
    "x"
  ]
}
```

---

## `dsp_ifft`

Compute the radix-2 IFFT of a frequency-domain sequence.

Input length must be a power of 2.

Input: { X: [{re, im}, ...] }
Returns: { ok, N, x: [{re, im}, ...] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "X": {
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
      "description": "Frequency-domain samples as [{re, im}] objects."
    }
  },
  "required": [
    "X"
  ]
}
```

---

## `dsp_spectrum`

Compute the one-sided DFT magnitude and phase spectrum of a real signal.

Returns N/2+1 frequency bins with magnitude (linear), magnitude (dB), phase (rad), and corresponding frequencies.

Input: { x: [number, ...], fs_hz: number }
Returns: { ok, N, fs_hz, freq_hz, magnitude, phase_rad, magnitude_db }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "x": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Real-valued time-domain samples. Length must be power of 2."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    }
  },
  "required": [
    "x",
    "fs_hz"
  ]
}
```

---

## `dsp_bin_frequency`

Return the frequency of DFT bin k for a length-N transform at sample rate fs.

freq = k × fs / N

Input: { k, N, fs_hz }
Returns: { ok, freq_hz, bin, N, fs_hz }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "k": {
      "type": "integer",
      "description": "Bin index (0 \u2264 k < N)."
    },
    "N": {
      "type": "integer",
      "description": "DFT length."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    }
  },
  "required": [
    "k",
    "N",
    "fs_hz"
  ]
}
```

---

## `dsp_fir_lp`

Design a windowed-sinc lowpass FIR filter.

The ideal sinc impulse response is multiplied by the chosen window to control stopband attenuation vs. transition bandwidth:
  rect:     −21 dB stopband,  narrowest transition
  hann:     −44 dB
  hamming:  −53 dB
  blackman: −74 dB, widest transition

Input: { N, fc_norm, window? }
Returns: { ok, N, fc_norm, window, h: [float, ...] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "N": {
      "type": "integer",
      "description": "Number of taps (use odd N for Type-I symmetric FIR)."
    },
    "fc_norm": {
      "type": "number",
      "description": "Normalised cutoff frequency fc/fs in (0, 0.5)."
    },
    "window": {
      "type": "string",
      "enum": [
        "rect",
        "hann",
        "hamming",
        "blackman"
      ],
      "description": "Window function (default 'hamming')."
    }
  },
  "required": [
    "N",
    "fc_norm"
  ]
}
```

---

## `dsp_fir_hp`

Design a windowed-sinc highpass FIR filter via spectral inversion.

h_hp[n] = δ[n − M/2] − h_lp[n]  (requires odd N).

Input: { N, fc_norm, window? }
Returns: { ok, N, fc_norm, window, h: [float, ...] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "N": {
      "type": "integer",
      "description": "Number of taps (must be odd)."
    },
    "fc_norm": {
      "type": "number",
      "description": "Normalised cutoff frequency fc/fs in (0, 0.5)."
    },
    "window": {
      "type": "string",
      "enum": [
        "rect",
        "hann",
        "hamming",
        "blackman"
      ],
      "description": "Window function (default 'hamming')."
    }
  },
  "required": [
    "N",
    "fc_norm"
  ]
}
```

---

## `dsp_fir_bp`

Design a windowed-sinc bandpass FIR filter.

Implemented as difference of two LP filters: h_bp = h_lp(fh) − h_lp(fl).

Input: { N, fl_norm, fh_norm, window? }
Returns: { ok, N, fl_norm, fh_norm, window, h: [float, ...] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "N": {
      "type": "integer",
      "description": "Number of taps."
    },
    "fl_norm": {
      "type": "number",
      "description": "Lower normalised cutoff in (0, 0.5)."
    },
    "fh_norm": {
      "type": "number",
      "description": "Upper normalised cutoff in (0, 0.5), must be > fl_norm."
    },
    "window": {
      "type": "string",
      "enum": [
        "rect",
        "hann",
        "hamming",
        "blackman"
      ],
      "description": "Window function (default 'hamming')."
    }
  },
  "required": [
    "N",
    "fl_norm",
    "fh_norm"
  ]
}
```

---

## `dsp_fir_order`

Estimate the minimum FIR tap count (N) for a given window and transition bandwidth using the fred-harris rule-of-thumb:

  N ≈ ceil(A / Δf_norm)

where A = 0.9/3.1/3.3/5.5 for rect/hann/hamming/blackman.

Input: { transition_bw_norm, window? }
Returns: { ok, N_estimate, window, transition_bw_norm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "transition_bw_norm": {
      "type": "number",
      "description": "Normalised transition bandwidth \u0394f/fs."
    },
    "window": {
      "type": "string",
      "enum": [
        "rect",
        "hann",
        "hamming",
        "blackman"
      ],
      "description": "Window function (default 'hamming')."
    }
  },
  "required": [
    "transition_bw_norm"
  ]
}
```

---

## `dsp_iir_butterworth_lp`

Design a digital Butterworth lowpass IIR filter using the bilinear transform with frequency prewarping.

Prewarping: ω_a = 2 tan(π f_c / f_s) ensures the digital −3 dB point is exactly at f_c.

Input: { order, fc_hz, fs_hz }
Returns: { ok, order, fc_hz, fs_hz, fc_norm, fc_prewarped_hz, b: [float,...], a: [float,...] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "order": {
      "type": "integer",
      "description": "Filter order (1\u201310).",
      "minimum": 1,
      "maximum": 10
    },
    "fc_hz": {
      "type": "number",
      "description": "\u22123 dB cutoff frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    }
  },
  "required": [
    "order",
    "fc_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_iir_butterworth_hp`

Design a digital Butterworth highpass IIR filter via bilinear transform.

Derived from the LP prototype by spectral inversion:
  b_hp[k] = b_lp[k] × (−1)^k,  a_hp[k] = a_lp[k] × (−1)^k

Input: { order, fc_hz, fs_hz }
Returns: { ok, order, fc_hz, fs_hz, fc_norm, fc_prewarped_hz, b, a }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "order": {
      "type": "integer",
      "description": "Filter order (1\u201310).",
      "minimum": 1,
      "maximum": 10
    },
    "fc_hz": {
      "type": "number",
      "description": "\u22123 dB cutoff frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    }
  },
  "required": [
    "order",
    "fc_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_biquad_lp`

Compute RBJ Audio EQ Cookbook lowpass biquad coefficients.

H(z) = (b0 + b1 z^-1 + b2 z^-2) / (1 + a1 z^-1 + a2 z^-2)

Input: { fc_hz, fs_hz, Q? }
Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "fc_hz": {
      "type": "number",
      "description": "Cutoff frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    },
    "Q": {
      "type": "number",
      "description": "Quality factor Q (default 0.7071 = 1/\u221a2 for Butterworth)."
    }
  },
  "required": [
    "fc_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_biquad_hp`

Compute RBJ Audio EQ Cookbook highpass biquad coefficients.

Input: { fc_hz, fs_hz, Q? }
Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "fc_hz": {
      "type": "number",
      "description": "Cutoff frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    },
    "Q": {
      "type": "number",
      "description": "Quality factor Q (default 0.7071)."
    }
  },
  "required": [
    "fc_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_biquad_bp`

Compute RBJ Audio EQ Cookbook bandpass biquad coefficients (0 dB peak at fc).

Input: { fc_hz, fs_hz, Q? }
Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "fc_hz": {
      "type": "number",
      "description": "Center frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    },
    "Q": {
      "type": "number",
      "description": "Quality factor Q (default 1.0)."
    }
  },
  "required": [
    "fc_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_biquad_notch`

Compute RBJ Audio EQ Cookbook notch (band-reject) biquad coefficients.

Input: { fc_hz, fs_hz, Q? }
Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "fc_hz": {
      "type": "number",
      "description": "Notch center frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    },
    "Q": {
      "type": "number",
      "description": "Quality factor Q (default 1.0)."
    }
  },
  "required": [
    "fc_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_biquad_peaking`

Compute RBJ Audio EQ Cookbook peaking EQ biquad coefficients.

Boosts (+) or cuts (−) gain_db around center frequency fc_hz.

Input: { fc_hz, fs_hz, Q?, gain_db? }
Returns: { ok, b: [b0,b1,b2], a: [1,a1,a2], fc_hz, fs_hz, Q, gain_db }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "fc_hz": {
      "type": "number",
      "description": "Center frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    },
    "Q": {
      "type": "number",
      "description": "Quality factor Q (default 1.0)."
    },
    "gain_db": {
      "type": "number",
      "description": "Boost/cut amount [dB] (default 6.0 dB)."
    }
  },
  "required": [
    "fc_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_freq_response`

Evaluate H(e^{jω}) of a digital filter at a single frequency.

Accepts any filter specified by its b/a difference-equation coefficients.

Input: { b: [float,...], a: [float,...], freq_hz, fs_hz }
Returns: { ok, freq_hz, fs_hz, magnitude, magnitude_db, phase_rad, H_re, H_im }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "b": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Numerator (feedforward) coefficients."
    },
    "a": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Denominator (feedback) coefficients."
    },
    "freq_hz": {
      "type": "number",
      "description": "Evaluation frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    }
  },
  "required": [
    "b",
    "a",
    "freq_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_group_delay`

Compute the group delay of a digital filter at a given frequency.

Approximated by central-difference of phase: −dφ/dω.

Input: { b, a, freq_hz, fs_hz, delta_hz? }
Returns: { ok, freq_hz, fs_hz, group_delay_samples, group_delay_s }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "b": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Numerator coefficients."
    },
    "a": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "Denominator coefficients."
    },
    "freq_hz": {
      "type": "number",
      "description": "Evaluation frequency [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    },
    "delta_hz": {
      "type": "number",
      "description": "Finite-difference step [Hz] (default 1.0 Hz)."
    }
  },
  "required": [
    "b",
    "a",
    "freq_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_nyquist_check`

Check whether a sample rate satisfies the Nyquist criterion for a signal bandwidth, and report the oversampling ratio.

Aliasing is flagged via warnings.warn and included in the response when fs ≤ 2 × signal_bw.

Input: { signal_bw_hz, fs_hz }
Returns: { ok, signal_bw_hz, fs_hz, nyquist_hz, oversampling_ratio, alias_free, recommended_fs_hz, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "signal_bw_hz": {
      "type": "number",
      "description": "Highest frequency component in the signal [Hz]."
    },
    "fs_hz": {
      "type": "number",
      "description": "Sample rate [Hz]."
    }
  },
  "required": [
    "signal_bw_hz",
    "fs_hz"
  ]
}
```

---

## `dsp_adc_snr`

Compute theoretical ADC performance metrics: SNR, ENOB, process gain.

  SNR_ideal = 6.02 × N + 1.76 dB  (N-bit full-scale sine)
  Process gain = 10 × log10(OSR) / 2  [3 dB per octave of oversampling]
  ENOB = (SNR_total − 1.76) / 6.02

Input: { bits, osr? }
Returns: { ok, bits, osr, snr_ideal_db, process_gain_db, snr_with_osr_db, enob, dynamic_range_db }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "bits": {
      "type": "integer",
      "description": "ADC resolution [bits] (1\u201332).",
      "minimum": 1,
      "maximum": 32
    },
    "osr": {
      "type": "number",
      "description": "Oversampling ratio (\u2265 1, default 1)."
    }
  },
  "required": [
    "bits"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
