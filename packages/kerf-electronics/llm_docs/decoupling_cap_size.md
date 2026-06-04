# electronics_recommend_decoupling_caps

*Module: `kerf_electronics.decoupling_cap_size` · Domain: electronics*

## Description

Recommend bulk + bypass decoupling capacitors for a digital IC power rail.

Uses Howard Johnson 'High-Speed Digital Design' §8.3 (target impedance) and Henry Ott 'Electromagnetic Compatibility Engineering' §13.3 (bulk charge balance + bypass rule of thumb).

Key formulas:
  Z_target = ΔV_droop / I_transient  (target PDN impedance)
  C_bulk   = I · t_rise / ΔV_droop   (minimum bulk capacitance)
  C_bypass = 100 nF per IC (≤50 MHz) / 10 nF per IC (>50 MHz)
  L_esl_max = Z_target / (2π · f_bw) per parallel cap  (ESL constraint)

HONEST: target-impedance heuristic only; PDN simulation (SPICE or pdn_decap_wizard) required for full anti-resonance and bank interaction validation.

Input: { voltage_V, max_transient_current_A, transient_rise_time_ns, max_droop_mV, signal_bandwidth_MHz, num_ICs }

Returns: { ok, target_impedance_mOhm, bulk_cap_uF, bypass_cap_uF, bypass_count, max_ESL_nH, max_ESR_mOhm, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "voltage_V": {
      "type": "number",
      "description": "Rail voltage [V] (e.g. 3.3, 1.8, 1.2)."
    },
    "max_transient_current_A": {
      "type": "number",
      "description": "Peak transient current step [A]."
    },
    "transient_rise_time_ns": {
      "type": "number",
      "description": "Current step rise time [ns]."
    },
    "max_droop_mV": {
      "type": "number",
      "description": "Maximum allowed voltage droop at IC pins [mV]."
    },
    "signal_bandwidth_MHz": {
      "type": "number",
      "description": "Target PDN bandwidth [MHz]."
    },
    "num_ICs": {
      "type": "integer",
      "description": "Number of ICs sharing this power rail."
    }
  },
  "required": [
    "voltage_V",
    "max_transient_current_A",
    "transient_rise_time_ns",
    "max_droop_mV",
    "signal_bandwidth_MHz",
    "num_ICs"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_recommend_decoupling_caps",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
