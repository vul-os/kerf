# gdt_compute_dimension_chain

*Module: `kerf_cad_core.gdt.dimension_chain` · Domain: cad*

## Description

Compute worst-case (WC) and statistical RSS tolerance stack-up for a linear dimension chain per ASME Y14.5-2018 §5.3.

A dimension chain is a closed loop of nominal dimensions whose sum determines the assembly gap (clearance or interference).  Each link has a bilateral tolerance (+t_plus / −t_minus) and a direction ('positive' adds to the gap, 'negative' subtracts).

Methods:
  Worst-case (WC): T_WC = Σ max(t⁺, t⁻); 100% assemblability, pessimistic.
  RSS (Statistical): T_RSS = √(Σ max(t⁺, t⁻)²); assumes independent, normally distributed links at 3σ — ~99.73% assemblability.

Returns:
  nominal_gap_mm        — Σ s_i · d_i
  worst_case_min/max_mm — [nominal − T_WC, nominal + T_WC]
  rss_min/max_mm        — [nominal − T_RSS, nominal + T_RSS]
  dominant_link         — link_id with largest half-tolerance
  honest_caveat         — RSS assumption flags

HONEST FLAG: RSS assumes independent normal distributions centred on nominal (Cpk=1.0); correlated or non-normal processes may be unconservative. Use WC for 100% guarantee; Monte Carlo for high-accuracy statistical results.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "chain": {
      "type": "array",
      "description": "Ordered list of dimension links forming the chain.",
      "items": {
        "type": "object",
        "properties": {
          "link_id": {
            "type": "string",
            "description": "Unique identifier for this link."
          },
          "nominal_mm": {
            "type": "number",
            "description": "Nominal dimension in mm (>= 0)."
          },
          "tol_plus_mm": {
            "type": "number",
            "description": "Upper tolerance half-band in mm (>= 0)."
          },
          "tol_minus_mm": {
            "type": "number",
            "description": "Lower tolerance half-band in mm (>= 0; sign is implied by name)."
          },
          "direction": {
            "type": "string",
            "enum": [
              "positive",
              "negative"
            ],
            "description": "'positive' \u2014 this link increases the gap; 'negative' \u2014 this link closes the gap."
          }
        },
        "required": [
          "link_id",
          "nominal_mm",
          "tol_plus_mm",
          "tol_minus_mm",
          "direction"
        ]
      },
      "minItems": 1
    },
    "target_gap_min_mm": {
      "type": "number",
      "description": "Required minimum assembly gap (mm)."
    },
    "target_gap_max_mm": {
      "type": "number",
      "description": "Required maximum assembly gap (mm, >= target_gap_min_mm)."
    }
  },
  "required": [
    "chain",
    "target_gap_min_mm",
    "target_gap_max_mm"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="gdt_compute_dimension_chain",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
