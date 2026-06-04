# bom_cost

*Module: `kerf_electronics.tools.bom_cost` · Domain: electronics*

This module registers **3** LLM tool(s):

- [`bom_cost_rollup`](#bom-cost-rollup)
- [`bom_dfm_report`](#bom-dfm-report)
- [`bom_sourcing_risk`](#bom-sourcing-risk)

---

## `bom_cost_rollup`

Compute extended BOM cost from a list of BOM line items. Selects the best price-break tier at the assembled quantity. Amortises NRE (non-recurring engineering) charges across the run. Excludes DNP (do-not-populate) parts from cost — mark a line with dnp=true or pass refdes names in the dnp_list argument. Returns: per-line extended cost, parts subtotal, NRE, total, per-board cost, and lists of DNP / missing-price lines. No live network calls — all computation is deterministic.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "bom_lines": {
      "type": "array",
      "description": "List of BOM line items. Each item: {refdes, qty, unit_price?, price_breaks?, dnp?, mpn?, description?, lead_time_weeks?, num_sources?, manufacturer?, distributor?}. price_breaks: [{min_qty, unit_price}, ...] sorted ascending.",
      "items": {
        "type": "object"
      }
    },
    "board_qty": {
      "type": "integer",
      "description": "Number of bare boards being manufactured (\u22651).",
      "minimum": 1
    },
    "assembly_qty": {
      "type": "integer",
      "description": "Number of boards to assemble with components. Defaults to board_qty. Price-break tier is selected at assembly_qty \u00d7 qty_per_board.",
      "minimum": 1
    },
    "nre_usd": {
      "type": "number",
      "description": "One-time NRE charges in USD (stencil, fixtures, setup). Amortised over assembly_qty. Default 0.",
      "minimum": 0
    },
    "dnp_list": {
      "type": "array",
      "description": "Additional refdes designators to treat as DNP regardless of line-level dnp flags. e.g. ['R5', 'C12'].",
      "items": {
        "type": "string"
      }
    }
  },
  "required": [
    "bom_lines"
  ]
}
```

---

## `bom_dfm_report`

Run IPC-class DFM (design-for-manufacture) rule checks on a CircuitJSON board and return a findings list plus a roll-up score (0–100, 100=clean). Rules checked: annular ring (PTH + via), min trace width/space, drill-to-copper, silkscreen-over-pad, acid traps, copper slivers, courtyard overlap, smallest passive size vs assembly capability. Thresholds follow IPC-2221B / IPC-A-600K for the selected board class. Pure-Python, no external tools required. board_class: 1=consumer, 2=commercial/industrial (default), 3=high-reliability.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_json": {
      "type": "array",
      "description": "Parsed CircuitJSON array from the board file.",
      "items": {
        "type": "object"
      }
    },
    "board_class": {
      "type": "integer",
      "description": "IPC board class: 1 (consumer), 2 (commercial, default), 3 (high-reliability / medical / aerospace).",
      "enum": [
        1,
        2,
        3
      ]
    }
  },
  "required": [
    "circuit_json"
  ]
}
```

---

## `bom_sourcing_risk`

Analyse BOM line items for sourcing risk: single-source parts, parts with no price information, and long-lead-time parts. Returns a risk list with severity (warn/fail) per line item. No live distributor calls — operates on the provided BOM data only. Input format is the same as bom_cost_rollup.bom_lines. long_lead_weeks threshold defaults to 16 weeks; single_source threshold is num_sources == 1.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "bom_lines": {
      "type": "array",
      "description": "List of BOM line items (same schema as bom_cost_rollup).",
      "items": {
        "type": "object"
      }
    },
    "long_lead_weeks": {
      "type": "number",
      "description": "Lead time (weeks) above which a part is flagged as long-lead. Default 16.",
      "minimum": 1
    }
  },
  "required": [
    "bom_lines"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
