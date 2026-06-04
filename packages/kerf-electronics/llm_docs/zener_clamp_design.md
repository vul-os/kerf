# electronics_design_zener_clamp

*Module: `kerf_electronics.zener_clamp_design` · Domain: electronics*

## Description

Design a Zener-diode voltage clamp (shunt regulator) + series resistor for a DC supply rail.

Computes R_series, peak Zener current, peak Zener power, and recommends a Zener package power rating and nearest E12 series resistor.

Topology: V_in → R_series → V_out ≈ V_zener, Zener shunts excess current.

Design equations (Horowitz & Hill §2.2.4 + Vishay AN-2014-3):
  R = (V_in_max − V_Z) / (I_load_min + I_zener_knee)
  I_Z_max = (V_in_max − V_Z_max) / R − I_load_min
  P_Z_design = V_Z × I_Z_max × 1.25  (25% derating margin)
  regulation_pct = 2 × V_zener_tolerance_pct

Zener packages: 0.4W (DO-35/SOD-80), 0.5W (DO-41), 1W (DO-41/BZX85), 3W (DO-201), 5W (SOT-89/TO-252).

HONEST: simple linear shunt regulator only — wasted power is constant regardless of load draw; Zener incremental resistance rZ NOT modelled; temperature coefficient of V_Z NOT modelled; for I_load > 100 mA prefer LDO or buck converter.

Input: { V_in_min_V, V_in_max_V, V_zener_V, I_load_min_A, I_load_max_A, [V_zener_tolerance_pct=5.0], [I_zener_knee_A=0.001] }

Returns: { ok, R_series_ohm, R_series_power_W, I_zener_max_A, P_zener_max_W, recommended_zener_package, recommended_R_E12_ohm, regulation_pct, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "V_in_min_V": {
      "type": "number",
      "description": "Minimum supply input voltage [V]. Must be > V_zener_V."
    },
    "V_in_max_V": {
      "type": "number",
      "description": "Maximum supply input voltage [V]."
    },
    "V_zener_V": {
      "type": "number",
      "description": "Nominal Zener breakdown voltage [V]."
    },
    "I_load_min_A": {
      "type": "number",
      "description": "Minimum DC load current [A]. May be 0."
    },
    "I_load_max_A": {
      "type": "number",
      "description": "Maximum DC load current [A]."
    },
    "V_zener_tolerance_pct": {
      "type": "number",
      "description": "Zener voltage tolerance [%], one-sided. Default 5.0 (\u00b15%, C-suffix). Use 2.0 for B-suffix, 1.0 for A-suffix."
    },
    "I_zener_knee_A": {
      "type": "number",
      "description": "Minimum Zener current to maintain hard regulation [A]. Default 0.001 A (1 mA). Vishay AN-2014-3 \u00a72 recommends 1\u20135% of I_Z_max."
    }
  },
  "required": [
    "V_in_min_V",
    "V_in_max_V",
    "V_zener_V",
    "I_load_min_A",
    "I_load_max_A"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_design_zener_clamp",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
