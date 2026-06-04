# thermal

*Module: `kerf_electronics.tools.thermal` · Domain: electronics*

This module registers **3** LLM tool(s):

- [`thermal_junction`](#thermal-junction)
- [`thermal_board_report`](#thermal-board-report)
- [`thermal_heatsink_required`](#thermal-heatsink-required)

---

## `thermal_junction`

Compute steady-state junction temperature for a single PCB component.

With heatsink:  Tj = Ta + P * (θjc + θcs + θsa)
Without:        Tj = Ta + P * θja

Thermal resistances in °C/W; power in W; temperatures in °C.

Returns {ok, tj_c, r_total, has_heatsink, over_limit, margin_c}.
over_limit is True when Tj > tj_max_c (only if tj_max_c is supplied).
margin_c = tj_max_c − tj_c (positive = safe).

Reference: TI SLVA462B 'Thermal Design by Insight, Not Hindsight'.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "power_w": {
      "type": "number",
      "description": "Component power dissipation in watts (>= 0)."
    },
    "ambient_c": {
      "type": "number",
      "description": "Ambient (board) temperature in \u00b0C."
    },
    "theta_ja": {
      "type": "number",
      "description": "Effective junction-to-ambient thermal resistance (\u00b0C/W). Required when theta_jc + theta_sa are not supplied (no-heatsink model)."
    },
    "theta_jc": {
      "type": "number",
      "description": "Junction-to-case thermal resistance (\u00b0C/W). Required for the heatsink model together with theta_sa."
    },
    "theta_cs": {
      "type": "number",
      "description": "Case-to-heatsink interface thermal resistance (\u00b0C/W). Defaults to 0 (no interface pad or ideal contact).",
      "default": 0.0
    },
    "theta_sa": {
      "type": "number",
      "description": "Heatsink-to-ambient thermal resistance (\u00b0C/W). Provide together with theta_jc to use the three-element chain. Omit for the theta_ja (no-heatsink) model."
    },
    "tj_max_c": {
      "type": "number",
      "description": "Maximum rated junction temperature from the component datasheet (\u00b0C). When supplied, the tool checks Tj against this limit and sets over_limit."
    }
  },
  "required": [
    "power_w",
    "ambient_c"
  ]
}
```

---

## `thermal_board_report`

Board-level thermal rollup: compute Tj for every component, sum total power dissipation, and flag any component whose Tj exceeds its Tj_max.

Each component entry uses the same thermal network model as thermal_junction:
  • Heatsink path:  Tj = Ta + P * (θjc + θcs + θsa)
  • No heatsink:    Tj = Ta + P * θja

Returns {ok, ambient_c, total_power_w, components[], worst_ref, worst_tj_c, any_over_limit}. Components list mirrors thermal_junction output per entry.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ambient_c": {
      "type": "number",
      "description": "Board ambient temperature in \u00b0C."
    },
    "components": {
      "type": "array",
      "description": "List of component thermal descriptors. Each item:\n  ref       (str)   \u2014 component reference, e.g. 'U1'\n  power_w   (num)   \u2014 dissipated power (W)\n  theta_ja  (num?)  \u2014 junction-to-ambient (\u00b0C/W)\n  theta_jc  (num?)  \u2014 junction-to-case (\u00b0C/W)\n  theta_cs  (num?)  \u2014 case-to-heatsink interface (\u00b0C/W), default 0\n  theta_sa  (num?)  \u2014 heatsink-to-ambient (\u00b0C/W)\n  tj_max_c  (num?)  \u2014 max rated junction temp (\u00b0C)",
      "items": {
        "type": "object",
        "properties": {
          "ref": {
            "type": "string"
          },
          "power_w": {
            "type": "number"
          },
          "theta_ja": {
            "type": "number"
          },
          "theta_jc": {
            "type": "number"
          },
          "theta_cs": {
            "type": "number"
          },
          "theta_sa": {
            "type": "number"
          },
          "tj_max_c": {
            "type": "number"
          }
        },
        "required": [
          "ref",
          "power_w"
        ]
      }
    }
  },
  "required": [
    "ambient_c",
    "components"
  ]
}
```

---

## `thermal_heatsink_required`

Back-calculate the maximum allowable heatsink-to-ambient resistance (θsa) to keep junction temperature at or below Tj_max.

Formula: θsa_max = (Tj_max − safety_margin − Ta) / P − θjc − θcs

Returns {ok, theta_sa_max_c_w, tj_target_c, feasible}.
feasible=False means no heatsink can meet the target at the given power/ambient; the design requires a lower-θjc package, reduced power, or active cooling.
When power_w=0, no heatsink is needed (note field is set).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "power_w": {
      "type": "number",
      "description": "Component power dissipation in watts (>= 0)."
    },
    "ambient_c": {
      "type": "number",
      "description": "Ambient temperature in \u00b0C."
    },
    "theta_jc": {
      "type": "number",
      "description": "Junction-to-case thermal resistance (\u00b0C/W)."
    },
    "tj_max_c": {
      "type": "number",
      "description": "Maximum rated junction temperature from datasheet (\u00b0C)."
    },
    "theta_cs": {
      "type": "number",
      "description": "Case-to-heatsink interface resistance (\u00b0C/W). Default 0.",
      "default": 0.0
    },
    "safety_margin_c": {
      "type": "number",
      "description": "Safety margin deducted from tj_max_c (\u00b0C). E.g. 10 means Tj_target = Tj_max \u2212 10 \u00b0C. Default 0.",
      "default": 0.0
    }
  },
  "required": [
    "power_w",
    "ambient_c",
    "theta_jc",
    "tj_max_c"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
