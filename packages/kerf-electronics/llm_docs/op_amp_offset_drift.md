# electronics_compute_op_amp_drift

*Module: `kerf_electronics.op_amp_offset_drift` · Domain: electronics*

## Description

Compute op-amp input offset voltage drift and output-referred error over a temperature range for precision instrumentation design.

Equations (TI 'Op Amp Errors' SLOA069 §3 + Analog Devices AN-580 §1):
  Vos(T) = Vos_typ + TC_Vos × (T − T_ref)      [µV]
  Vos_max_IR = max(|Vos(T_min)|, |Vos(T_max)|)  [µV, input-referred]
  Vos_OR = gain × Vos_max_IR / 1000             [mV, output-referred]
  error_pct = 100 × (Vos_OR / 1000) / FS_V     [% of full scale]

Recommends op-amp class: 'standard' (TC>1 µV/°C), 'precision' (TC≤1 µV/°C), 'zero-drift' (TC≤0.1 µV/°C), 'chopper' (TC≤0.05 µV/°C).

HONEST: linear drift model only — real drift is non-linear and asymmetric (TI SLOA069 Fig 3-2); 1/f noise NOT modelled; PSRR/CMRR cross-talk OUT OF SCOPE; resistor TC mismatch NOT included. Use Vos_max (not Vos_typ) for guaranteed worst-case analysis.

Input: { Vos_typ_uV, Vos_drift_uV_per_C, T_ambient_min_C, T_ambient_max_C, [T_reference_C=25], gain_VV, signal_full_scale_V, [error_budget_pct=0.1] }

Returns: { ok, Vos_at_T_min_uV, Vos_at_T_max_uV, Vos_max_input_referred_uV, Vos_max_output_referred_mV, error_pct_of_FS, within_spec, recommended_op_amp_class, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "Vos_typ_uV": {
      "type": "number",
      "description": "Typical input offset voltage at T_reference_C [\u00b5V]. Positive or negative per datasheet polarity. Use |Vos_max| for worst-case design margin."
    },
    "Vos_drift_uV_per_C": {
      "type": "number",
      "description": "Offset voltage temperature coefficient TC_Vos [\u00b5V/\u00b0C], magnitude (always \u2265 0). Typical: 0.05 (chopper), 0.1\u20131 (precision), 1\u201310 (general-purpose)."
    },
    "T_ambient_min_C": {
      "type": "number",
      "description": "Minimum ambient operating temperature [\u00b0C]. e.g. 0 (commercial), -40 (industrial/automotive)."
    },
    "T_ambient_max_C": {
      "type": "number",
      "description": "Maximum ambient operating temperature [\u00b0C]. e.g. 70 (commercial), 85 (industrial), 125 (automotive)."
    },
    "T_reference_C": {
      "type": "number",
      "description": "Reference temperature at which Vos_typ is specified [\u00b0C]. Default 25 \u00b0C."
    },
    "gain_VV": {
      "type": "number",
      "description": "Closed-loop gain magnitude [V/V]. Must be \u2265 1. For non-inverting: 1+Rf/Rg. For inverting: Rf/Rg."
    },
    "signal_full_scale_V": {
      "type": "number",
      "description": "Signal full-scale range [V] for % error calculation. e.g. 10.0 for \u00b15V ADC range, 3.3 for 0\u20133.3V unipolar."
    },
    "error_budget_pct": {
      "type": "number",
      "description": "Allowable output offset error as % of full scale [%]. Default 0.1% (approx 1 LSB of 10-bit ADC at FS)."
    }
  },
  "required": [
    "Vos_typ_uV",
    "Vos_drift_uV_per_C",
    "T_ambient_min_C",
    "T_ambient_max_C",
    "gain_VV",
    "signal_full_scale_V"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_compute_op_amp_drift",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
