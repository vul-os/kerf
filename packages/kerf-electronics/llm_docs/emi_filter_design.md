# electronics_design_emi_filter

*Module: `kerf_electronics.emi_filter_design` · Domain: electronics*

## Description

Design a passive LC or RC power-line EMI filter.

Computes the corner frequency, inductance, capacitance (or resistance), and attenuation at a target conducted-emission frequency for one of three topologies:
  • LC_low_pass  — 2nd-order series-L / shunt-C (−40 dB/decade; Ott §15.3)
  • PI_LC_L      — π-section: shunt-C, series-L, shunt-C (−60 dB/decade)
  • RC_low_pass  — 1st-order RC (−20 dB/decade; signal/bypass lines only)

Design equations:
  LC: f_c = f_t / 10^(A/40);  C = 1/((2π·f_c)²·L) for L=100 µH
  PI: f_c = f_t / 10^(A/60);  same C formula; each shunt cap = C/2
  RC: f_c = f_t / 10^(A/20);  C = 1/(2π·f_c·R)

Also returns nearest E12 X2 (275 VAC) capacitor values from CISPR 22 §6.2.

HONEST: ideal passive components only — no ESR, no parasitic inductance of capacitors, no winding stray capacitance; DM-only (add separate CM choke for common-mode); source/load assumed ideal; CISPR 22 Class B conducted limits cited for context only — compliance requires accredited EMC lab measurement (CISPR 22 / EN 55022).

Input: { dc_voltage_V, dc_current_A, target_attenuation_dB, target_freq_kHz, filter_topology, [load_resistance_ohm] }

Returns: { ok, cutoff_freq_Hz, L_uH, C_uF, R_ohm, attenuation_at_target_dB, recommended_caps_X2_uF, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "dc_voltage_V": {
      "type": "number",
      "description": "DC bus voltage the filter must handle [V]."
    },
    "dc_current_A": {
      "type": "number",
      "description": "DC (or peak AC) current through the series element [A]."
    },
    "target_attenuation_dB": {
      "type": "number",
      "description": "Required insertion loss at the target conducted-emission frequency [dB], e.g. 30 dB for 30 dB of suppression."
    },
    "target_freq_kHz": {
      "type": "number",
      "description": "Target conducted-emission frequency [kHz]; CISPR 22 range starts at 150 kHz."
    },
    "filter_topology": {
      "type": "string",
      "enum": [
        "LC_low_pass",
        "PI_LC_L",
        "RC_low_pass"
      ],
      "description": "Filter topology: 'LC_low_pass' (2nd-order, \u221240 dB/dec), 'PI_LC_L' (\u03c0-section, \u221260 dB/dec), or 'RC_low_pass' (1st-order, \u221220 dB/dec; signal lines only)."
    },
    "load_resistance_ohm": {
      "type": "number",
      "description": "Load resistance [\u03a9]. Only used for RC_low_pass (sets R). Default 50 \u03a9 if omitted."
    }
  },
  "required": [
    "dc_voltage_V",
    "dc_current_A",
    "target_attenuation_dB",
    "target_freq_kHz",
    "filter_topology"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_design_emi_filter",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
