# ac_impedance

*Module: `kerf_electronics.pdn.ac_impedance` · Domain: electronics*

This module registers **2** LLM tool(s):

- [`pdn_ac_impedance_sweep`](#pdn-ac-impedance-sweep)
- [`pdn_recommend_decaps`](#pdn-recommend-decaps)

---

## `pdn_ac_impedance_sweep`

Frequency-domain PDN AC impedance analysis.

Sweeps Z(ω) from DC to GHz for a parallel combination of VRM, bulk caps, MLCCs, and a PCB plane model. Returns |Z| at each frequency and a target-impedance pass/fail check.

Input: { v_supply, i_max, ripple_pct, f_min_hz?, f_max_hz?, n_pts?, vrm?, bulk_caps?, mlccs?, plane? }

Each mlcc: { c, r_esr, l_esl, l_mount?, count? }
Each bulk_cap: { c, r_esr, l_esl, count? }
vrm: { r_out, l_out, bw_hz? }
plane: { side_m, height_m, eps_r? }

Returns: { ok, z_target_ohm, meets_target, worst_peak_ohm, worst_peak_hz, violating_bands[], freqs_hz[], z_mag_ohm[] }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_supply": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "i_max": {
      "type": "number",
      "description": "Peak transient current [A]."
    },
    "ripple_pct": {
      "type": "number",
      "description": "Allowed ripple [%] (e.g. 5.0)."
    },
    "f_min_hz": {
      "type": "number",
      "description": "Sweep start [Hz] (default 1e3)."
    },
    "f_max_hz": {
      "type": "number",
      "description": "Sweep end [Hz] (default 1e9)."
    },
    "n_pts": {
      "type": "integer",
      "description": "Number of sweep points (default 500)."
    },
    "vrm": {
      "type": "object",
      "description": "VRM model {r_out, l_out, bw_hz?}.",
      "properties": {
        "r_out": {
          "type": "number"
        },
        "l_out": {
          "type": "number"
        },
        "bw_hz": {
          "type": "number"
        }
      }
    },
    "bulk_caps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number"
          },
          "r_esr": {
            "type": "number"
          },
          "l_esl": {
            "type": "number"
          },
          "count": {
            "type": "integer"
          }
        },
        "required": [
          "c",
          "r_esr",
          "l_esl"
        ]
      }
    },
    "mlccs": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number"
          },
          "r_esr": {
            "type": "number"
          },
          "l_esl": {
            "type": "number"
          },
          "l_mount": {
            "type": "number"
          },
          "count": {
            "type": "integer"
          }
        },
        "required": [
          "c",
          "r_esr",
          "l_esl"
        ]
      }
    },
    "plane": {
      "type": "object",
      "description": "PCB plane model {side_m, height_m, eps_r?}.",
      "properties": {
        "side_m": {
          "type": "number"
        },
        "height_m": {
          "type": "number"
        },
        "eps_r": {
          "type": "number"
        }
      }
    }
  },
  "required": [
    "v_supply",
    "i_max",
    "ripple_pct"
  ]
}
```

---

## `pdn_recommend_decaps`

Greedy decap-bank optimiser for PDN target impedance.

Iteratively adds the cheapest available capacitor whose self-resonant frequency is nearest the worst-violating frequency, until Z ≤ Z_target or the cap library is exhausted.

Input: { v_supply, i_max, ripple_pct, f_min_hz?, f_max_hz?, n_pts?, available_caps[] }

Each cap: { c, r_esr, l_esl, l_mount?, cost_each?, name? }

Returns: { ok, recommended[], total_cost, meets_target, iterations }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_supply": {
      "type": "number"
    },
    "i_max": {
      "type": "number"
    },
    "ripple_pct": {
      "type": "number"
    },
    "f_min_hz": {
      "type": "number"
    },
    "f_max_hz": {
      "type": "number"
    },
    "n_pts": {
      "type": "integer"
    },
    "available_caps": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "c": {
            "type": "number"
          },
          "r_esr": {
            "type": "number"
          },
          "l_esl": {
            "type": "number"
          },
          "l_mount": {
            "type": "number"
          },
          "cost_each": {
            "type": "number"
          },
          "name": {
            "type": "string"
          }
        },
        "required": [
          "c",
          "r_esr",
          "l_esl"
        ]
      }
    }
  },
  "required": [
    "v_supply",
    "i_max",
    "ripple_pct",
    "available_caps"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
