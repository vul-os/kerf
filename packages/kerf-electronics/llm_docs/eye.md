# eye

*Module: `kerf_electronics.tools.eye` · Domain: electronics*

This module registers **3** LLM tool(s):

- [`eye_estimate`](#eye-estimate)
- [`jitter_budget`](#jitter-budget)
- [`eye_mask_check`](#eye-mask-check)

---

## `eye_estimate`

Compute a first-order statistical eye diagram for a lossy PCB serial channel. Returns normalised eye height (vertical opening), eye width in UI, vertical eye closure (VEC), horizontal eye closure (HEC), total insertion loss, attenuation, received rise time, and intermediate details. Channel model: insertion-loss at Nyquist sets attenuation; ISI and reflections add vertical penalty; channel bandwidth widens the received rise time. References: Johnson & Graham 2003 §3.4/§3.7; Bogatin 2004 §7. Input shape: { loss_db_per_inch, length_inch, bit_rate_bps, rise_time_tx_s, isi_fraction?, reflection_gamma? }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "loss_db_per_inch": {
      "type": "number",
      "description": "Insertion loss at Nyquist frequency [dB/inch]. Typical FR4: 0.3\u20130.8 dB/inch at 5 GHz."
    },
    "length_inch": {
      "type": "number",
      "description": "Channel (trace) length [inches]."
    },
    "bit_rate_bps": {
      "type": "number",
      "description": "Signalling bit rate [bits/s], e.g. 10e9 for 10 Gbps."
    },
    "rise_time_tx_s": {
      "type": "number",
      "description": "Transmitter 10\u201390% rise time [seconds], e.g. 50e-12 for 50 ps."
    },
    "isi_fraction": {
      "type": "number",
      "description": "Fractional ISI penalty relative to ideal eye height (0\u2013<1). Default: 0.05 (5%). Use 0 for an ideal channel."
    },
    "reflection_gamma": {
      "type": "number",
      "description": "Magnitude of the dominant reflection coefficient |\u0393| (0\u20131). Default: 0.0 (no reflections). Obtain via si_impedance + reflection coefficient formula."
    }
  },
  "required": [
    "loss_db_per_inch",
    "length_inch",
    "bit_rate_bps",
    "rise_time_tx_s"
  ]
}
```

---

## `jitter_budget`

Compute total jitter (Tj) decomposition: Tj = Dj + 2·Rj·Q(BER). Rj is random jitter (1-sigma, Gaussian); Dj is deterministic jitter (peak-to-peak). Q(BER) is the Q-factor for the target bit-error ratio. Inputs may be in any consistent unit (seconds, ps, UI). Reference: Li, 'Jitter, Noise, and Signal Integrity at High-Speed', Prentice Hall 2007, §2.3 eq. 2-6. Input shape: { rj_s, dj_s, ber? }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "rj_s": {
      "type": "number",
      "description": "Random jitter 1-sigma value. May be in seconds, ps, or UI \u2014 consistent with dj_s."
    },
    "dj_s": {
      "type": "number",
      "description": "Deterministic jitter peak-to-peak value (same unit as rj_s). Must be >= 0."
    },
    "ber": {
      "type": "number",
      "description": "Target bit-error ratio, e.g. 1e-12 for telecom grade. Must be in (0, 0.5). Default: 1e-12."
    }
  },
  "required": [
    "rj_s",
    "dj_s"
  ]
}
```

---

## `eye_mask_check`

Check whether a computed eye diagram passes a rectangular eye mask. The eye passes when eye_height >= mask height AND eye_width_ui >= mask width. An optional vertical offset reduces the effective eye height. Returns pass/fail, height margin, and width margin. Input shape: { eye: <eye_estimate result>, mask: { height, width_ui, voffset? } }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "eye": {
      "type": "object",
      "description": "Eye diagram result dict from eye_estimate tool (must contain 'ok', 'eye_height', 'eye_width_ui')."
    },
    "mask": {
      "type": "object",
      "description": "Rectangular mask definition: { 'height': <min eye height>, 'width_ui': <min eye width in UI>, 'voffset': <optional vertical centre offset> }.",
      "properties": {
        "height": {
          "type": "number",
          "description": "Minimum required eye height (normalised, >= 0)."
        },
        "width_ui": {
          "type": "number",
          "description": "Minimum required eye width [UI] (>= 0)."
        },
        "voffset": {
          "type": "number",
          "description": "Vertical offset of mask centre (default: 0.0)."
        }
      },
      "required": [
        "height",
        "width_ui"
      ]
    }
  },
  "required": [
    "eye",
    "mask"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
