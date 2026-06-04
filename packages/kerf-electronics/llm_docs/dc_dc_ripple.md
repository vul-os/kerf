# electronics_compute_buck_ripple

*Module: `kerf_electronics.dc_dc_ripple` · Domain: electronics*

## Description

Compute output voltage ripple (ΔV_out, peak-to-peak) for a buck DC-DC converter in Continuous Conduction Mode (CCM).

Equations (Erickson 'Fundamentals of Power Electronics' 3e §2.4):
  D       = V_out / V_in
  ΔiL     = (V_in − V_out) · D / (L · f_sw)     [inductor ripple, A pp]
  ΔV_cap  = ΔiL / (8 · C · f_sw)                [capacitor ripple, V pp]
  ΔV_ESR  = ΔiL · ESR                            [ESR ripple, V pp]
  ΔV_out  = ΔV_cap + ΔV_ESR                      [worst-case total, V pp]

Also reports: duty_cycle, output_ripple_pct, CCM validity flag.

HONEST: CCM only — DCM not modelled; small-ripple approximation flagged when ΔiL > 30% of 2·I_load; D assumes ideal converter (no deadtime/loss); ESR assumed flat at f_sw; ΔV_out is pessimistic linear sum. Refs: Erickson 3e §2.4; Sandler §3.

Input: { V_in_V, V_out_V, I_load_A, switching_freq_Hz, L_uH, C_out_uF, C_ESR_mOhm }

Returns: { ok, delta_iL_pp_A, delta_V_out_pp_mV, delta_V_capacitor_mV, delta_V_ESR_mV, duty_cycle, output_ripple_pct, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "V_in_V": {
      "type": "number",
      "description": "Input supply voltage [V]."
    },
    "V_out_V": {
      "type": "number",
      "description": "Output voltage [V]. Must be less than V_in_V."
    },
    "I_load_A": {
      "type": "number",
      "description": "DC load current [A]. Used for CCM boundary check."
    },
    "switching_freq_Hz": {
      "type": "number",
      "description": "Switching frequency [Hz], e.g. 500000 for 500 kHz."
    },
    "L_uH": {
      "type": "number",
      "description": "Filter inductance [\u00b5H]."
    },
    "C_out_uF": {
      "type": "number",
      "description": "Output filter capacitance [\u00b5F]."
    },
    "C_ESR_mOhm": {
      "type": "number",
      "description": "Equivalent series resistance (ESR) of the output capacitor [m\u03a9]. Use datasheet ESR at the switching frequency. Set to 0 for ideal capacitor."
    }
  },
  "required": [
    "V_in_V",
    "V_out_V",
    "I_load_A",
    "switching_freq_Hz",
    "L_uH",
    "C_out_uF",
    "C_ESR_mOhm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_compute_buck_ripple",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
