# pdn_wizard

*Module: `kerf_electronics.pdn_wizard` · Domain: electronics*

This module registers **2** LLM tool(s):

- [`pdn_decap_wizard`](#pdn-decap-wizard)
- [`pdn_characterise_cap`](#pdn-characterise-cap)

---

## `pdn_decap_wizard`

Power-delivery-network (PDN) decoupling-capacitor wizard.

Computes Z_target = (Vdd × ripple_frac) / I_transient, builds the PDN impedance spectrum from DC to the target bandwidth (VRM + bulk + ceramic decap banks), finds parallel-resonance (anti-resonance) peaks that exceed Z_target, and recommends a minimal decoupling set (count & value mix across decades) so |Z(f)| ≤ Z_target.

Input: { vdd_v, ripple_frac, i_transient_a, bw_hz, l_vrm_h?, r_vrm_ohm?, l_plane_h?, banks? }

Returns: { ok, z_target_ohm, meets_target, bandwidth_met_hz, anti_resonance_peaks[], recommended_banks[], per_bank_srf[], sweep{freqs_hz,z_mag_ohm}, summary }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "vdd_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "ripple_frac": {
      "type": "number",
      "description": "Allowed ripple as fraction of Vdd (e.g. 0.05 for 5%)."
    },
    "i_transient_a": {
      "type": "number",
      "description": "Peak transient current [A]."
    },
    "bw_hz": {
      "type": "number",
      "description": "Target PDN bandwidth [Hz]."
    },
    "l_vrm_h": {
      "type": "number",
      "description": "VRM output inductance [H] (default 10 nH)."
    },
    "r_vrm_ohm": {
      "type": "number",
      "description": "VRM output resistance [\u03a9] (default 5 m\u03a9)."
    },
    "l_plane_h": {
      "type": "number",
      "description": "Plane spreading inductance per cap [H] (default 0.5 nH)."
    },
    "banks": {
      "type": "array",
      "description": "Cap banks: list of {cap_f, esr_ohm, esl_h, mount_l_h?, count}. Omit to use synthesised defaults.",
      "items": {
        "type": "object",
        "properties": {
          "cap_f": {
            "type": "number"
          },
          "esr_ohm": {
            "type": "number"
          },
          "esl_h": {
            "type": "number"
          },
          "mount_l_h": {
            "type": "number"
          },
          "count": {
            "type": "integer"
          }
        },
        "required": [
          "cap_f",
          "esr_ohm",
          "esl_h"
        ]
      }
    }
  },
  "required": [
    "vdd_v",
    "ripple_frac",
    "i_transient_a",
    "bw_hz"
  ]
}
```

---

## `pdn_characterise_cap`

Characterise a single decoupling capacitor: compute self-resonant frequency (f_srf = 1/(2π√(L_total·C))), |Z| at SRF, and the DC/HF asymptote behaviour.

Input: { cap_f, esr_ohm, esl_h, mount_l_h? }

Returns: { ok, srf_hz, z_at_srf_ohm, l_total_h, dc_asymptote, hf_asymptote }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "cap_f": {
      "type": "number",
      "description": "Capacitance [F]."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Equivalent series resistance [\u03a9]."
    },
    "esl_h": {
      "type": "number",
      "description": "Equivalent series inductance [H]."
    },
    "mount_l_h": {
      "type": "number",
      "description": "Mounting/via inductance [H] (default 0)."
    }
  },
  "required": [
    "cap_f",
    "esr_ohm",
    "esl_h"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
