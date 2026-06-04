# elec_compute_zener_drift

*Module: `kerf_electronics.zener_tc_drift` · Domain: electronics*

## Description

Compute Zener diode voltage drift over temperature using the temperature coefficient (TC) in mV/°C.

Models the Vz vs T curve which has a zero-TC crossing near 5.6 V (above: positive TC dominated by avalanche; below: negative TC dominated by Zener tunneling). Per Vishay AN-2014-3 §2.4, ON AN-961 §3, and Sze 'Physics of Semiconductor Devices' §4.5.

Typical TC values:
  3.3 V Zener → TC ≈ −2 mV/°C (tunneling regime)
  5.6 V Zener → TC ≈ 0 mV/°C  (transition/near-zero TC)
  12 V Zener  → TC ≈ +8 mV/°C (avalanche regime)

Algorithm:
  rZ ≈ 0.01 × Vz_nom / Iz_test [Ω]  (Vishay AN-2014-3 §2.2)
  ΔVz_current = rZ × (Iz_op − Iz_test)  [V]
  Vz(T) = (Vz_nom + ΔVz_current) + TC × 10⁻³ × (T − T_test)  [V]
  drift_percent = 100 × |Vz(T_max) − Vz(T_min)| / Vz_nom

Recommendation: drift > 5% → suggest 5.6 V near-zero TC Zener or bandgap Vref IC.

HONEST: LINEAR TC MODEL ONLY — real Vz vs T is mildly quadratic in the 5–7 V transition region; thermal self-heating NOT modelled; TC is current-dependent and has part-to-part spread.

Input: { Vz_nominal_V, TC_mV_per_C, test_current_mA, [test_temp_C=25.0], current_mA, ambient_temp_C_min, ambient_temp_C_max }

Returns: { ok, Vz_at_min_temp_V, Vz_at_max_temp_V, Vz_drift_total_V, Vz_drift_percent, current_dependence_warning, recommendation, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "Vz_nominal_V": {
      "type": "number",
      "description": "Nominal Zener breakdown voltage at datasheet test conditions [V]. Typical range 1.8\u201347 V."
    },
    "TC_mV_per_C": {
      "type": "number",
      "description": "Temperature coefficient of Vz [mV/\u00b0C], SIGNED. Negative for tunneling-dominated Zeners (Vz < ~5 V), positive for avalanche-dominated (Vz > ~7 V). Typical: \u22122 for 3.3 V, ~0 for 5.6 V, +8 for 12 V."
    },
    "test_current_mA": {
      "type": "number",
      "description": "Datasheet test current at which Vz_nominal is specified [mA]. Typically 5\u201320 mA for small-signal Zeners."
    },
    "test_temp_C": {
      "type": "number",
      "description": "Reference / datasheet test temperature [\u00b0C]. Default 25 \u00b0C (JEDEC)."
    },
    "current_mA": {
      "type": "number",
      "description": "Actual operating current through the Zener [mA]."
    },
    "ambient_temp_C_min": {
      "type": "number",
      "description": "Minimum ambient temperature in the application [\u00b0C]."
    },
    "ambient_temp_C_max": {
      "type": "number",
      "description": "Maximum ambient temperature in the application [\u00b0C]."
    }
  },
  "required": [
    "Vz_nominal_V",
    "TC_mV_per_C",
    "test_current_mA",
    "current_mA",
    "ambient_temp_C_min",
    "ambient_temp_C_max"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="elec_compute_zener_drift",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
