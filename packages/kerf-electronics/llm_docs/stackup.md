# stackup

*Module: `kerf_electronics.stackup.tools` · Domain: electronics*

This module registers **17** LLM tool(s):

- [`stackup_copper_weight`](#stackup-copper-weight)
- [`stackup_microstrip_z0`](#stackup-microstrip-z0)
- [`stackup_embedded_microstrip_z0`](#stackup-embedded-microstrip-z0)
- [`stackup_stripline_z0_symmetric`](#stackup-stripline-z0-symmetric)
- [`stackup_stripline_z0_asymmetric`](#stackup-stripline-z0-asymmetric)
- [`stackup_cpwg_z0`](#stackup-cpwg-z0)
- [`stackup_diff_microstrip_z0`](#stackup-diff-microstrip-z0)
- [`stackup_diff_stripline_z0`](#stackup-diff-stripline-z0)
- [`stackup_effective_er`](#stackup-effective-er)
- [`stackup_propagation_delay`](#stackup-propagation-delay)
- [`stackup_wavelength`](#stackup-wavelength)
- [`stackup_trace_width_solver`](#stackup-trace-width-solver)
- [`stackup_diff_spacing_solver`](#stackup-diff-spacing-solver)
- [`stackup_conductor_loss`](#stackup-conductor-loss)
- [`stackup_dielectric_loss`](#stackup-dielectric-loss)
- [`stackup_thickness`](#stackup-thickness)
- [`stackup_impedance_budget`](#stackup-impedance-budget)

---

## `stackup_copper_weight`

Convert PCB copper weight [oz/ft²] to foil thickness [µm and mm].

Industry standard (IPC-6012 §3.2): 1 oz/ft² = 34.8 µm.

Common copper weights: 0.5 oz (17.5 µm), 1 oz (35 µm), 2 oz (70 µm).

Input: { oz }
Returns: { ok, oz, thickness_mm, thickness_um }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "oz": {
      "type": "number",
      "description": "Copper weight [oz/ft\u00b2], e.g. 0.5, 1.0, 2.0."
    }
  },
  "required": [
    "oz"
  ]
}
```

---

## `stackup_microstrip_z0`

Compute single-ended microstrip characteristic impedance Z0 [Ω].

Model: Hammerstad-Jensen closed-form with trace-thickness correction (Wadell §3.4 / IPC-2141A eq. 1-1/1-2).

Typical 50 Ω microstrip on FR-4 (er=4.3, H=0.2 mm): W ≈ 0.44 mm.

Fab-range warnings issued for W < 0.075 mm or H < 0.05 mm.

Input: { W_mm, H_mm, er, T_mm? }
Returns: { ok, Z0, er_eff, W_mm, H_mm, er, T_mm, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "H_mm": {
      "type": "number",
      "description": "Dielectric height above reference plane [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity (e.g. 4.3 for FR-4)."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm = 1 oz copper)."
    }
  },
  "required": [
    "W_mm",
    "H_mm",
    "er"
  ]
}
```

---

## `stackup_embedded_microstrip_z0`

Compute embedded microstrip Z0 [Ω] (trace with a dielectric cover layer).

The cover layer increases er_eff vs. open microstrip, lowering Z0.
Model: Wadell §3.4.4: er_eff_emb = er_eff * (1 - exp(-1.55 * d / H)).
For d=0 this equals standard microstrip.

Input: { W_mm, H_mm, er, d_mm, T_mm? }
Returns: { ok, Z0, er_eff, er_eff_embedded, W_mm, H_mm, er, d_mm, T_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "H_mm": {
      "type": "number",
      "description": "Dielectric height above reference plane [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "d_mm": {
      "type": "number",
      "description": "Cover layer thickness above the trace [mm] (0 = open microstrip)."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    }
  },
  "required": [
    "W_mm",
    "H_mm",
    "er",
    "d_mm"
  ]
}
```

---

## `stackup_stripline_z0_symmetric`

Compute symmetric stripline Z0 [Ω] (trace centred between two ground planes).

Model: IPC-2141A eq. 2-1 / Wadell §4.3.
Formula: Z0 = (60/√er) × ln(4B / (0.67π(0.8W + T)))
where B = total dielectric thickness between reference planes.

Typical 50 Ω stripline on FR-4 (er=4.3, B=0.4 mm, T=0.035 mm): W ≈ 0.20 mm.

Input: { W_mm, B_mm, er, T_mm? }
Returns: { ok, Z0, er_eff, W_mm, B_mm, er, T_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "B_mm": {
      "type": "number",
      "description": "Total dielectric thickness between both reference planes [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    }
  },
  "required": [
    "W_mm",
    "B_mm",
    "er"
  ]
}
```

---

## `stackup_stripline_z0_asymmetric`

Compute asymmetric stripline Z0 [Ω] (trace at unequal distances from two planes).

Model: Wadell §4.5 (eqn 4.5-3). Accurate within ~5% for c/b ∈ [0.5, 2.0].

b = distance from trace to top reference plane [mm]
c = distance from trace to bottom reference plane [mm]

Input: { W_mm, b_mm, c_mm, er, T_mm? }
Returns: { ok, Z0, er_eff, W_mm, b_mm, c_mm, er, T_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "b_mm": {
      "type": "number",
      "description": "Distance from trace to top reference plane [mm]."
    },
    "c_mm": {
      "type": "number",
      "description": "Distance from trace to bottom reference plane [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    }
  },
  "required": [
    "W_mm",
    "b_mm",
    "c_mm",
    "er"
  ]
}
```

---

## `stackup_cpwg_z0`

Compute coplanar-waveguide-with-ground (CPWG) characteristic impedance Z0 [Ω].

Model: Hammerstad-Jensen conformal-mapping (Wadell §5.2) with Hilberg elliptic integral approximation.

Input: { W_mm, G_mm, H_mm, er, T_mm? }
where G_mm = gap between signal conductor and coplanar ground.
Returns: { ok, Z0, er_eff, W_mm, G_mm, H_mm, er, T_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W_mm": {
      "type": "number",
      "description": "Signal conductor width [mm]."
    },
    "G_mm": {
      "type": "number",
      "description": "Gap to coplanar ground planes [mm]."
    },
    "H_mm": {
      "type": "number",
      "description": "Substrate height to back-side reference [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    }
  },
  "required": [
    "W_mm",
    "G_mm",
    "H_mm",
    "er"
  ]
}
```

---

## `stackup_diff_microstrip_z0`

Compute differential microstrip impedance Zdiff [Ω] (Wadell §3.7).

Formula: Zdiff = 2 × Z0 × (1 − 0.347 × exp(−2.9 × S/H))
where S = edge-to-edge spacing and Z0 = single-ended microstrip Z0.

Typical 100 Ω differential pair on FR-4 (H=0.2 mm, er=4.3): W ≈ 0.18 mm, S ≈ 0.20 mm.

Input: { W_mm, S_mm, H_mm, er, T_mm? }
Returns: { ok, Z0_single, Zdiff, er_eff, W_mm, S_mm, H_mm, er, T_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "S_mm": {
      "type": "number",
      "description": "Edge-to-edge spacing between traces [mm]."
    },
    "H_mm": {
      "type": "number",
      "description": "Dielectric height [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    }
  },
  "required": [
    "W_mm",
    "S_mm",
    "H_mm",
    "er"
  ]
}
```

---

## `stackup_diff_stripline_z0`

Compute differential symmetric stripline impedance Zdiff [Ω] (Wadell §4.3).

Formula: Zdiff = 2 × Z0 × (1 − 0.347 × exp(−2.9 × S/B))

Input: { W_mm, S_mm, B_mm, er, T_mm? }
Returns: { ok, Z0_single, Zdiff, er_eff, W_mm, S_mm, B_mm, er, T_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "S_mm": {
      "type": "number",
      "description": "Edge-to-edge spacing [mm]."
    },
    "B_mm": {
      "type": "number",
      "description": "Total dielectric thickness [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    }
  },
  "required": [
    "W_mm",
    "S_mm",
    "B_mm",
    "er"
  ]
}
```

---

## `stackup_effective_er`

Compute effective dielectric constant er_eff for a PCB transmission-line structure.

Structures: 'microstrip', 'embedded_microstrip', 'stripline', 'cpwg'.

Input: { structure, W_mm, H_mm, er, T_mm?, d_mm?, G_mm? }
Returns: { ok, er_eff, structure, W_mm, H_mm, er }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "structure": {
      "type": "string",
      "enum": [
        "microstrip",
        "embedded_microstrip",
        "stripline",
        "cpwg"
      ],
      "description": "Transmission-line structure type."
    },
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "H_mm": {
      "type": "number",
      "description": "Dielectric height (microstrip/CPWG) or total B (stripline) [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    },
    "d_mm": {
      "type": "number",
      "description": "Cover layer thickness [mm] (embedded_microstrip only)."
    },
    "G_mm": {
      "type": "number",
      "description": "Gap to coplanar ground [mm] (CPWG only, default 0.1 mm)."
    }
  },
  "required": [
    "structure",
    "W_mm",
    "H_mm",
    "er"
  ]
}
```

---

## `stackup_propagation_delay`

Compute propagation delay Td [ps/mm] from effective dielectric constant.

Formula: Td = sqrt(er_eff) / c  where c = 0.2998 mm/ps.

Typical values:
  Free space (er_eff=1): Td ≈ 3.33 ps/mm
  FR-4 microstrip (er_eff≈3.0): Td ≈ 5.77 ps/mm
  FR-4 stripline (er_eff=er=4.3): Td ≈ 6.95 ps/mm

Input: { er_eff }
Returns: { ok, er_eff, Td_ps_per_mm, Td_ns_per_m }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "er_eff": {
      "type": "number",
      "description": "Effective relative permittivity (from any Z0 function)."
    }
  },
  "required": [
    "er_eff"
  ]
}
```

---

## `stackup_wavelength`

Compute guided wavelength λ [mm] on a transmission line at a given frequency.

λ = c / (f × sqrt(er_eff))  where c = 299.792 mm/ns.

Also returns λ/4 (quarter-wave stub length) and λ/10 (rule-of-thumb for distributed effects).

Input: { freq_hz, er_eff }
Returns: { ok, freq_hz, er_eff, wavelength_mm, quarter_wave_mm, tenth_wave_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "er_eff": {
      "type": "number",
      "description": "Effective relative permittivity."
    }
  },
  "required": [
    "freq_hz",
    "er_eff"
  ]
}
```

---

## `stackup_trace_width_solver`

Solve for the trace width [mm] that achieves a target Z0 using bisection.

Works for microstrip and symmetric stripline.
Warns and sets unrealizable=True when the target Z0 cannot be achieved in the search range W ∈ [0.01, 20] mm.

Input: { Z0_target, H_mm, er, structure?, T_mm?, B_mm? }
Returns: { ok, W_mm, Z0_achieved, Z0_target, er_eff, iterations, unrealizable, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Z0_target": {
      "type": "number",
      "description": "Target characteristic impedance [\u03a9]."
    },
    "H_mm": {
      "type": "number",
      "description": "Dielectric height [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "structure": {
      "type": "string",
      "enum": [
        "microstrip",
        "stripline"
      ],
      "description": "Transmission-line structure (default 'microstrip')."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    },
    "B_mm": {
      "type": "number",
      "description": "Total dielectric thickness for stripline [mm] (overrides H_mm)."
    }
  },
  "required": [
    "Z0_target",
    "H_mm",
    "er"
  ]
}
```

---

## `stackup_diff_spacing_solver`

Solve for the trace spacing [mm] that achieves a target differential impedance Zdiff using bisection.

Warns and sets unrealizable=True when the target cannot be achieved.

Input: { Zdiff_target, W_mm, H_mm, er, structure?, T_mm?, B_mm? }
Returns: { ok, S_mm, Zdiff_achieved, Zdiff_target, Z0_single, iterations, unrealizable, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Zdiff_target": {
      "type": "number",
      "description": "Target differential impedance [\u03a9]."
    },
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "H_mm": {
      "type": "number",
      "description": "Dielectric height [mm]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "structure": {
      "type": "string",
      "enum": [
        "microstrip",
        "stripline"
      ],
      "description": "Transmission-line structure (default 'microstrip')."
    },
    "T_mm": {
      "type": "number",
      "description": "Trace thickness [mm] (default 0.035 mm)."
    },
    "B_mm": {
      "type": "number",
      "description": "Total dielectric thickness for stripline [mm]."
    }
  },
  "required": [
    "Zdiff_target",
    "W_mm",
    "H_mm",
    "er"
  ]
}
```

---

## `stackup_conductor_loss`

Compute conductor (skin-effect) attenuation [dB/mm] vs frequency.

Model: Hammerstad-Jensen (Wadell §3.5):
  Rs = sqrt(π f μ₀ ρ)       [surface resistance Ω/sq]
  αc = Rs / (π W Z0)        [Np/m → dB/mm]

Surface roughness correction (Huray/IPC-2141A):
  δs = sqrt(ρ / (π f μ₀))   [skin depth]
  rough_factor = 1 + (2/π) × arctan(1.4 × (roughness/δs)²)

Input: { freq_hz, W_mm, Z0, roughness_um?, rho_relative? }
Returns: { ok, alpha_c_db_per_mm, alpha_c_rough_db_per_mm, skin_depth_um, roughness_factor, Rs_ohm_sq }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "W_mm": {
      "type": "number",
      "description": "Trace width [mm]."
    },
    "Z0": {
      "type": "number",
      "description": "Characteristic impedance [\u03a9]."
    },
    "roughness_um": {
      "type": "number",
      "description": "RMS surface roughness [\u00b5m] (0 = ideal smooth, default 0)."
    },
    "rho_relative": {
      "type": "number",
      "description": "Resistivity relative to copper (default 1.0)."
    }
  },
  "required": [
    "freq_hz",
    "W_mm",
    "Z0"
  ]
}
```

---

## `stackup_dielectric_loss`

Compute dielectric (loss-tangent) attenuation [dB/mm] vs frequency.

Model (Wadell §3.5-12 / Pozar Eq. 3.30):
  αd = 27.3 × (er/√er_eff)(er_eff−1)/(er−1) × tan_d × f_GHz / c_mm_ns

For stripline (er_eff = er):
  αd = 27.3 × √er × tan_d × f_GHz / 299.792 dB/mm

Typical FR-4 tan_d = 0.020 at 1 GHz.

Input: { freq_hz, er, er_eff, tan_d }
Returns: { ok, freq_hz, er, er_eff, tan_d, alpha_d_db_per_mm }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Frequency [Hz]."
    },
    "er": {
      "type": "number",
      "description": "Substrate relative permittivity."
    },
    "er_eff": {
      "type": "number",
      "description": "Effective relative permittivity."
    },
    "tan_d": {
      "type": "number",
      "description": "Loss tangent of the substrate (e.g. 0.020 for FR-4 at 1 GHz)."
    }
  },
  "required": [
    "freq_hz",
    "er",
    "er_eff",
    "tan_d"
  ]
}
```

---

## `stackup_thickness`

Compute total PCB thickness from a list of stackup layers.

Each layer: { type: 'dielectric'|'copper', thickness_mm: float, name?: str }

Returns total, copper, and dielectric thickness plus a layer-by-layer summary.

Input: { layers: [{type, thickness_mm, name?}, ...] }
Returns: { ok, total_thickness_mm, copper_thickness_mm, dielectric_thickness_mm, layer_count, layers_summary }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "layers": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "type": {
            "type": "string",
            "enum": [
              "dielectric",
              "copper"
            ],
            "description": "Layer material type."
          },
          "thickness_mm": {
            "type": "number",
            "description": "Layer thickness [mm]."
          },
          "name": {
            "type": "string",
            "description": "Optional layer name (e.g. 'Core', 'L1-Cu')."
          }
        },
        "required": [
          "type",
          "thickness_mm"
        ]
      },
      "description": "Ordered list of stackup layers from top to bottom."
    }
  },
  "required": [
    "layers"
  ]
}
```

---

## `stackup_impedance_budget`

Compute Z0 for every controlled-impedance net in a multilayer stackup and flag any that fall outside the impedance tolerance.

Each net: { name, structure, W_mm, H_mm, er, T_mm?, S_mm?, target_z0? }
structure: 'microstrip' | 'stripline' | 'differential_microstrip' | 'differential_stripline'

Warnings are issued (not raised) for any out-of-budget nets.

Input: { nets: [...], tolerance_pct? }
Returns: { ok, nets_results, all_in_budget, out_of_budget_names, tolerance_pct }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "nets": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "structure": {
            "type": "string",
            "enum": [
              "microstrip",
              "stripline",
              "differential_microstrip",
              "differential_stripline"
            ]
          },
          "W_mm": {
            "type": "number"
          },
          "H_mm": {
            "type": "number"
          },
          "er": {
            "type": "number"
          },
          "T_mm": {
            "type": "number"
          },
          "S_mm": {
            "type": "number"
          },
          "target_z0": {
            "type": "number"
          }
        },
        "required": [
          "name",
          "structure",
          "W_mm",
          "H_mm",
          "er"
        ]
      },
      "description": "List of controlled-impedance nets to evaluate."
    },
    "tolerance_pct": {
      "type": "number",
      "description": "Allowed deviation from target_z0 [%] (default 10%)."
    }
  },
  "required": [
    "nets"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
