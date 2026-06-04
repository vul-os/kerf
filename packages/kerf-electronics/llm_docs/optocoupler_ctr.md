# elec_analyze_optocoupler

*Module: `kerf_electronics.optocoupler_ctr` · Domain: electronics*

## Description

Analyze an optocoupler isolation circuit: given LED forward current IF, CTR (min/typ/max), pull-up resistor R_L, supply Vcc, and load capacitance C_L, computes:
  - IC_min/typ/max [mA] = CTR/100 × IF (IEC 60747-5-5 §6.3)
  - IC_saturation_mA = Vcc / R_L (output saturation threshold)
  - saturated_min_case: IC_min >= IC_sat (worst-case is saturated)
  - Vout_low = Vce_sat (datasheet), Vout_high = Vcc
  - t_rise/fall [µs] = max(2.2×R_L×C_L, datasheet spec scaled by R_L)
  - headroom_factor_min = IC_min / IC_sat
  - warnings (over-drive, under-drive, marginal headroom)

References: Vishay AN-38; Avago AN-5078; IEC 60747-5-5:2007 §6.3.

HONEST: LINEAR CTR MODEL ONLY — real CTR vs IF is non-linear; temperature derating and LED aging (30–50% CTR loss over lifetime) NOT modelled.

Input: { model, IF_mA, CTR_min_percent, CTR_typ_percent, CTR_max_percent, IF_max_mA, Vcc_out_V, R_pullup_ohm, [Vce_sat_V=0.2], [Vf_typ_V=1.2], [C_load_pF=20.0], [R_LED_series_ohm=0], [V_LED_drive_V=0], [t_rise_us_at_Rl=[2.0, 1000]] }

Returns: { ok, IC_min_mA, IC_typ_mA, IC_max_mA, IC_saturation_mA, saturated_min_case, Vout_low_V, Vout_high_V, t_rise_us, t_fall_us, headroom_factor_min, warnings, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "model": {
      "type": "string",
      "description": "Optocoupler part number / model name (e.g. '4N35', 'PC817')."
    },
    "IF_mA": {
      "type": "number",
      "description": "LED forward current delivered to the LED in circuit [mA]."
    },
    "CTR_min_percent": {
      "type": "number",
      "description": "Minimum current transfer ratio at IF_mA [%]."
    },
    "CTR_typ_percent": {
      "type": "number",
      "description": "Typical current transfer ratio at IF_mA [%]."
    },
    "CTR_max_percent": {
      "type": "number",
      "description": "Maximum current transfer ratio at IF_mA [%]."
    },
    "IF_max_mA": {
      "type": "number",
      "description": "Maximum rated LED forward current [mA] (for over-drive warning)."
    },
    "Vcc_out_V": {
      "type": "number",
      "description": "Output-side supply voltage [V] (collector pull-up supply)."
    },
    "R_pullup_ohm": {
      "type": "number",
      "description": "Pull-up resistor from Vcc to collector [\u03a9]."
    },
    "Vce_sat_V": {
      "type": "number",
      "description": "Collector-emitter saturation voltage [V]. Default 0.2 V."
    },
    "Vf_typ_V": {
      "type": "number",
      "description": "Typical LED forward voltage [V]. Default 1.2 V."
    },
    "C_load_pF": {
      "type": "number",
      "description": "Load capacitance at collector node [pF]. Default 20 pF."
    },
    "R_LED_series_ohm": {
      "type": "number",
      "description": "Series resistor on the LED input side [\u03a9]. Used with V_LED_drive_V to cross-check IF. Default 0."
    },
    "V_LED_drive_V": {
      "type": "number",
      "description": "Drive voltage applied to the LED + series resistor [V]. Used with R_LED_series_ohm to cross-check IF. Default 0."
    },
    "t_rise_us_at_Rl": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[t_rise_us, R_L_spec_ohm]: datasheet rise time [\u00b5s] at a reference R_L [\u03a9]. Scaled linearly to actual R_pullup_ohm. Default [2.0, 1000]. Set t_rise_us=0 to use RC model only."
    }
  },
  "required": [
    "IF_mA",
    "CTR_min_percent",
    "CTR_typ_percent",
    "CTR_max_percent",
    "IF_max_mA",
    "Vcc_out_V",
    "R_pullup_ohm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="elec_analyze_optocoupler",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
