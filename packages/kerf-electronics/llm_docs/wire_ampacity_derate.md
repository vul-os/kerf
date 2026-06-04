# electronics_compute_derated_ampacity

*Module: `kerf_electronics.tools.wire_ampacity_derate` · Domain: electronics*

## Description

Compute the effective installation ampacity of a conductor after applying NEC 2023 Article 310 derating:
  1. Ambient temperature correction — NEC Table 310.15(B)(2)(a), 75°C column.
  2. Conductor bundling adjustment — NEC Table 310.15(B)(3)(a).

Effective ampacity = base_ampacity_A × C_ambient × C_bundling.

References:
  • NEC 2023 Table 310.16 (caller supplies base ampacity from 75°C column).
  • NEC 2023 Table 310.15(B)(2)(a): ambient correction — ≤30°C→1.00, 31–35°C→0.94, 36–40°C→0.88, 41–45°C→0.82, 46–50°C→0.75, 51–55°C→0.67, 56–60°C→0.58.
  • NEC 2023 Table 310.15(B)(3)(a): bundling — 1–3→1.00, 4–6→0.80, 7–9→0.70, 10–20→0.50, 21–30→0.45, 31–40→0.40, 41+→0.35.

Honest caveats:
  • 75°C insulation column only (THWN/THHN/XHHW/RHW). NEC 110.14(C) terminal rating limits most ≤100 A circuits to 75°C regardless of insulation rating.
  • Rooftop adder, underground/buried, and Type NM cable derating NOT modelled.
  • Free-air installation (Table 310.17) NOT covered — set in_conduit=false and supply Table 310.17 base ampacity.
  • Ambient > 60°C: outside table range — raises an error.

Input: { awg_size, material, insulation_class, base_ampacity_A, ambient_temp_C, num_current_carrying_conductors?, in_conduit? }
Returns: { ok, base_ampacity_A, ambient_correction_factor, bundling_factor, effective_ampacity_A, conditions_summary, code_section_cited, honest_caveat }

## Input schema

```json
{
  "type": "object",
  "properties": {
    "awg_size": {
      "type": "string",
      "description": "AWG conductor size string, e.g. '14', '12', '10', '8', '6', '4', '2', '1', '1/0', '2/0', '3/0', '4/0', '250kcmil'. Used for documentation in the report; the base_ampacity_A value must match the corresponding NEC Table 310.16 entry."
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
        "TW",
        "THWN",
        "THHN",
        "XHHW",
        "RHW"
      ],
      "description": "Insulation type. THWN/THHN/XHHW/RHW are all 75\u00b0C rated and use the 75\u00b0C correction column. TW is 60\u00b0C \u2014 apply with caution (this module uses 75\u00b0C correction factors)."
    },
    "base_ampacity_A": {
      "type": "number",
      "description": "Conductor base ampacity from NEC Table 310.16, 75\u00b0C column, \u22643 conductors in conduit, 30\u00b0C ambient [A]. Example: 12 AWG copper THWN \u2192 25 A; 10 AWG copper \u2192 35 A."
    },
    "ambient_temp_C": {
      "type": "number",
      "description": "Actual ambient temperature at the installation site [\u00b0C]. NEC Table 310.15(B)(2)(a) correction factor is applied. Supported: \u2264 60\u00b0C. Values \u2264 30\u00b0C yield correction factor 1.00."
    },
    "num_current_carrying_conductors": {
      "type": "integer",
      "description": "Total number of current-carrying conductors sharing the conduit, raceway, or cable bundle. Default 1. Values 1\u20133 yield a bundling factor of 1.00 (already in Table 310.16). 4\u20136 \u2192 0.80, 7\u20139 \u2192 0.70, 10\u201320 \u2192 0.50, 21\u201330 \u2192 0.45, 31\u201340 \u2192 0.40, 41+ \u2192 0.35."
    },
    "in_conduit": {
      "type": "boolean",
      "description": "True (default) if conductors share a conduit, raceway, or are otherwise bundled \u2014 bundling derating applies. False for free-air installations (Table 310.17); no bundling derating is applied but the caller must supply a Table 310.17 base ampacity."
    }
  },
  "required": [
    "awg_size",
    "material",
    "insulation_class",
    "base_ampacity_A",
    "ambient_temp_C"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="electronics_compute_derated_ampacity",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_electronics`
