# electronics_check_inductor_saturation

*Module: `kerf_electronics.inductor_core_saturation` · Domain: electronics*

## Description

Check whether an inductor's magnetic core is saturated given the core material, geometry (A_e, l_e, B_sat), turn count N, and peak DC + ripple current.

Formula (Ampere's law, closed uniform magnetic path):
  I_pk   = I_dc + I_ripple_pp / 2
  B_pk   = μ₀ · μ_r · N · I_pk / l_e     [l_e in metres]
  margin = (B_sat − B_pk) / B_sat × 100   [%]

Temperature derating: B_sat is reduced for ferrite materials above 25°C
  (piecewise-linear: 100°C→−15%, 125°C→−25%, 150°C→−40%, 200°C→−50%
  per Ferroxcube 3C95/3F36 datasheets). Not applied to powder-iron/Sendust/NiFe.

Reports: B_peak_mT, B_sat_mT (derated), saturation_margin_pct, saturated,
recommended_max_I_dc_A (1% guard-band), honest_caveat.

HONEST: fringing flux around air gaps ignored; μ_r assumed constant (real ferrite μ_r rolls off in knee region BEFORE B_sat — model is conservative/over-estimates B_pk); non-ferrite B_sat derating NOT modelled; winding I²R heating NOT accounted for; AC core losses NOT computed.

Refs: Erickson 'Power Electronics' 3e §15; McLyman 'Transformer and Inductor Design Handbook' 4e §10; Ferroxcube 3C95/3F36 datasheets.

Input: { material, A_e_mm2, l_e_mm, B_sat_mT, mu_r, turns_N, I_dc_A, I_ripple_peak_to_peak_A, [temperature_C=25.0] }

Returns: { ok, B_peak_mT, B_sat_mT, saturation_margin_pct, saturated, recommended_max_I_dc_A, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "material": {
      "type": "string",
      "description": "Core material identifier. Supported: 'ferrite_3C95', 'ferrite_3F36', 'powdered_iron_-26', 'sendust', 'NiFe50'. For custom materials provide B_sat_mT and mu_r explicitly."
    },
    "A_e_mm2": {
      "type": "number",
      "description": "Effective core cross-sectional area [mm\u00b2]. Must be > 0. From the core datasheet (e.g. ETD49 \u2192 211 mm\u00b2). Not used in the saturation formula but captured for reference."
    },
    "l_e_mm": {
      "type": "number",
      "description": "Effective magnetic path length [mm]. Must be > 0. From the core datasheet (e.g. ETD49 \u2192 114 mm)."
    },
    "B_sat_mT": {
      "type": "number",
      "description": "Saturation flux density at 25\u00b0C [mT]. Must be > 0. Typical: ferrite_3C95 \u2248 500 mT, ferrite_3F36 \u2248 380 mT, powdered_iron_-26 \u2248 1400 mT, sendust \u2248 1000 mT, NiFe50 \u2248 1600 mT."
    },
    "mu_r": {
      "type": "number",
      "description": "Initial relative permeability of the core (small-signal). Must be > 0. Typical: ferrite_3C95 \u2248 2000, ferrite_3F36 \u2248 1500, powdered_iron_-26 \u2248 75, sendust \u2248 125, NiFe50 \u2248 3000. NOTE: real ferrite \u03bc_r rolls off significantly before B_sat \u2014 this model uses a constant \u03bc_r (conservative/over-estimates B_pk)."
    },
    "turns_N": {
      "type": "integer",
      "description": "Number of turns. Must be >= 1."
    },
    "I_dc_A": {
      "type": "number",
      "description": "DC bias (average) current [A]. Must be >= 0."
    },
    "I_ripple_peak_to_peak_A": {
      "type": "number",
      "description": "Peak-to-peak AC ripple current [A]. Must be >= 0. Peak current = I_dc + I_ripple_pp / 2."
    },
    "temperature_C": {
      "type": "number",
      "description": "Core operating temperature [\u00b0C]. Default 25.0. Used for B_sat derating (ferrite materials only). Elevated temperature reduces B_sat significantly for ferrites."
    }
  },
  "required": [
    "A_e_mm2",
    "l_e_mm",
    "B_sat_mT",
    "mu_r",
    "turns_N",
    "I_dc_A",
    "I_ripple_peak_to_peak_A"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_check_inductor_saturation",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
