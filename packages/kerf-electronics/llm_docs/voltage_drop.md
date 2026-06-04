# electronics_check_voltage_drop

*Module: `kerf_electronics.tools.voltage_drop` · Domain: electronics*

## Description

Compute voltage drop across a conductor run and verify NEC 2023 Article 210.19(A) Informational Note 4 compliance.

References:
  • NEC 2023 Article 210.19(A) Informational Note 4: recommended ≤ 3% feeder, ≤ 2% branch circuit.
  • NEC 2023 Chapter 9 Table 8: DC conductor resistance at 75°C.
  • IEEE 141-1993 §3.3: voltage-drop formulas.

Formulas (IEEE 141 §3.3):
  DC / single-phase: V_drop = 2 × I × R [Ω/m] × L [m] × PF
  Three-phase:       V_drop = √3 × I × R [Ω/m] × L [m] × PF

Supported AWG sizes: 14, 12, 10, 8, 6, 4, 2, 1, 1/0, 2/0, 3/0, 4/0, 250kcmil
Materials: copper | aluminum (1.64× copper per Table 8)

Honest caveats:
  • Resistance at 75°C baseline — no ambient temperature correction.
  • AC reactance (X_L) ignored; may underestimate by 5–15% for ≥ 1/0 AWG.
  • NEC 210.19(A) Note 4 is advisory, not mandatory.

Input: { awg_size, material, length_one_way_m, voltage_V, current_A, phase, power_factor?, max_drop_pct? }
Returns: { ok, voltage_drop_V, voltage_drop_pct, recommended_max_pct, compliant, resistance_ohm, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "awg_size": {
      "type": "string",
      "enum": [
        "14",
        "12",
        "10",
        "8",
        "6",
        "4",
        "2",
        "1",
        "1/0",
        "2/0",
        "3/0",
        "4/0",
        "250kcmil"
      ],
      "description": "AWG conductor size. Use '250kcmil' for 250 kcmil. NEC Chapter 9 Table 8 supports 14 AWG\u20134/0 and 250\u2013750 kcmil; this tool covers the most common range."
    },
    "material": {
      "type": "string",
      "enum": [
        "copper",
        "aluminum"
      ],
      "description": "Conductor material: 'copper' or 'aluminum'."
    },
    "length_one_way_m": {
      "type": "number",
      "description": "One-way conductor run length [m]. Round-trip is computed internally."
    },
    "voltage_V": {
      "type": "number",
      "description": "System voltage [V] (used as denominator for Vd%)."
    },
    "current_A": {
      "type": "number",
      "description": "Load current [A]."
    },
    "phase": {
      "type": "string",
      "enum": [
        "dc",
        "single_phase",
        "three_phase"
      ],
      "description": "'dc' for DC circuits (2-wire, round-trip), 'single_phase' for single-phase AC (2-wire), 'three_phase' for balanced 3-phase AC."
    },
    "power_factor": {
      "type": "number",
      "description": "Power factor (0 < PF \u2264 1.0). Use 1.0 for DC or purely resistive loads (default 1.0). Typical: 0.85\u20130.95 for motors."
    },
    "max_drop_pct": {
      "type": "number",
      "description": "Maximum allowable voltage drop percentage. Default 3.0 per NEC 210.19(A) Informational Note 4 feeder limit. Use 2.0 for branch-circuit check."
    },
    "ambient_temp_C": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C] (default 30.0). Documented for future temperature-correction support; the 75\u00b0C NEC Table 8 baseline is used as-is in this version."
    }
  },
  "required": [
    "awg_size",
    "material",
    "length_one_way_m",
    "voltage_V",
    "current_A",
    "phase"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_check_voltage_drop",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
