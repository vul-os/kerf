# electronics_check_circuit_protection

*Module: `kerf_electronics.tools.circuit_protection` · Domain: electronics*

## Description

Verify that an overcurrent protective device (OCPD) is correctly sized for a conductor and load per NEC 2023 Articles 240 and 215.

References:
  • NEC 2023 Table 310.16 (75°C column): conductor ampacity for THWN/THHN/XHHW/RHW insulation, ≤3 current-carrying conductors in conduit, 30°C ambient.
  • NEC 2023 Article 240.4(B): OCPD ≤ conductor ampacity.
  • NEC 2023 Article 240.4(D): small conductor rule — 14 AWG Cu → max 15 A, 12 AWG Cu → max 20 A, 10 AWG Cu → max 30 A.
  • NEC 2023 Article 215.3 / 210.20(A): required OCPD ≥ 1.25 × continuous_current + non_continuous_current.

Supported AWG sizes: 14, 12, 10, 8, 6, 4, 3, 2, 1, 1/0, 2/0, 3/0, 4/0, 250kcmil, 300kcmil, 500kcmil
Materials: copper | aluminum
Insulation (all 75°C): THWN | THHN | XHHW | RHW

Honest caveats:
  • 75°C THWN baseline — no ambient temperature derating (NEC 310.15(B)(2)(a)).
  • No bundling derating (NEC Table 310.15(B)(3)(a)).
  • Short-circuit withstand, arc-flash, and grounding are out of scope.

Input: { awg_size, material, insulation_class, continuous_current_A, non_continuous_current_A, voltage_V, phase, breaker_rating_A, breaker_type? }
Returns: { ok, ampacity_A, required_ocpd_min_A, derated_ampacity_A, ocpd_compliant, conductor_adequate, code_section_cited, honest_caveat }

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
        "3",
        "2",
        "1",
        "1/0",
        "2/0",
        "3/0",
        "4/0",
        "250kcmil",
        "300kcmil",
        "500kcmil"
      ],
      "description": "Conductor AWG or kcmil size.  Use '250kcmil' for 250 kcmil, etc. NEC Table 310.16 covers AWG 14\u20134/0 and 250\u2013750 kcmil; this tool covers the most common range."
    },
    "material": {
      "type": "string",
      "enum": [
        "copper",
        "aluminum"
      ],
      "description": "Conductor material."
    },
    "insulation_class": {
      "type": "string",
      "enum": [
        "THWN",
        "THHN",
        "XHHW",
        "RHW"
      ],
      "description": "Insulation type \u2014 all four carry a 75\u00b0C rating and use the same NEC Table 310.16 75\u00b0C column."
    },
    "continuous_current_A": {
      "type": "number",
      "description": "Portion of load current that flows continuously (\u2265 3 h) [A]. NEC 100 definition of continuous load."
    },
    "non_continuous_current_A": {
      "type": "number",
      "description": "Portion of load current that is NOT continuous [A]."
    },
    "voltage_V": {
      "type": "number",
      "description": "System voltage [V] (informational, not used in NEC 240.4 calc)."
    },
    "phase": {
      "type": "string",
      "enum": [
        "single_phase",
        "three_phase"
      ],
      "description": "Circuit phase configuration (informational)."
    },
    "breaker_rating_A": {
      "type": "number",
      "description": "Nominal OCPD rating [A] (breaker trip rating or fuse ampere rating)."
    },
    "breaker_type": {
      "type": "string",
      "enum": [
        "standard",
        "hacr",
        "slow_blow"
      ],
      "description": "OCPD type.  'standard' = standard inverse-time circuit breaker; 'hacr' = HACR-rated breaker (heating/air-conditioning/refrigeration); 'slow_blow' = time-delay fuse.  Default 'standard'."
    }
  },
  "required": [
    "awg_size",
    "material",
    "insulation_class",
    "continuous_current_A",
    "non_continuous_current_A",
    "voltage_V",
    "phase",
    "breaker_rating_A"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_check_circuit_protection",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
