# electronics_check_ldo_dropout

*Module: `kerf_electronics.ldo_dropout_check` · Domain: electronics*

## Description

Verify that an LDO (Low-Dropout) linear regulator operates correctly given input voltage range, output voltage, load current, and LDO dropout voltage specification.

Equations (TI Power Reference Manual §3 + Sandler 'Switch-Mode Power Supplies' §4):
  headroom_mV        = (V_in_min − V_out) × 1000   [worst-case margin]
  dropout_compliant  = headroom_mV > dropout_spec_mV
  P_diss             = (V_in_max − V_out) × I_load  [worst-case power, W]
  T_j                = T_ambient + P_diss × R_θja   [junction temp, °C]
  thermal_compliant  = T_j < T_max_junction
  efficiency_pct     = 100 × V_out / V_in_max       [pessimistic, ignores I_Q]

HONEST: quiescent current NOT modelled; transient headroom NOT checked; output capacitor stability NOT verified; θja is worst-case single-node thermal model (Jedec JESD51). Refs: TI Power Ref §3; Sandler §4; Jedec JESD51-1.

Input: { V_out_V, V_in_min_V, V_in_max_V, I_load_A, dropout_voltage_at_max_load_mV, junction_to_ambient_thermal_resistance_K_per_W, [T_ambient_C=25], [T_max_junction_C=125] }

Returns: { ok, headroom_min_mV, dropout_compliant, power_dissipation_W, junction_temp_estimate_C, thermal_compliant, efficiency_pct, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "V_out_V": {
      "type": "number",
      "description": "Regulated output voltage [V]. Must be > 0."
    },
    "V_in_min_V": {
      "type": "number",
      "description": "Minimum input supply voltage [V]. Used for worst-case dropout headroom check. Must be > V_out_V."
    },
    "V_in_max_V": {
      "type": "number",
      "description": "Maximum input supply voltage [V]. Used for worst-case power dissipation. Must be >= V_in_min_V."
    },
    "I_load_A": {
      "type": "number",
      "description": "Maximum load current [A]. Must be > 0."
    },
    "dropout_voltage_at_max_load_mV": {
      "type": "number",
      "description": "LDO dropout voltage at maximum load current [mV]. From device datasheet (V_DO at I_out_max). Must be > 0."
    },
    "junction_to_ambient_thermal_resistance_K_per_W": {
      "type": "number",
      "description": "Thermal resistance \u03b8ja (junction-to-ambient) [K/W or \u00b0C/W]. From device datasheet for the specific package. Must be > 0."
    },
    "T_ambient_C": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C]. Default 25.0."
    },
    "T_max_junction_C": {
      "type": "number",
      "description": "Maximum rated junction temperature [\u00b0C]. Default 125.0. Use 150.0 for automotive-grade (AEC-Q100 Grade 1) devices."
    }
  },
  "required": [
    "V_out_V",
    "V_in_min_V",
    "V_in_max_V",
    "I_load_A",
    "dropout_voltage_at_max_load_mV",
    "junction_to_ambient_thermal_resistance_K_per_W"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_check_ldo_dropout",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
