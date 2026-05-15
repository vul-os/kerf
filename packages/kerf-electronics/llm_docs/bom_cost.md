# BOM Cost / Sourcing Rollup + DFM Report

Three LLM tools for cost analysis and design-for-manufacture review of CircuitJSON boards.
All are pure-Python with no network calls; results are deterministic.

---

## `bom_cost_rollup`

Computes extended BOM cost across a production run.

**Key features:**
- Selects the best price-break tier at `assembly_qty × qty_per_board`
- Amortises one-time NRE (stencil, fixtures, test) over the run
- Excludes DNP parts (via per-line `dnp: true` flag or `dnp_list` argument)
- Reports per-board cost and flags lines with missing prices

**Input** — `bom_lines` (array of line items):
```json
{
  "refdes": "R1,R2",
  "qty": 2,
  "unit_price": 0.10,
  "price_breaks": [
    {"min_qty": 1,   "unit_price": 0.15},
    {"min_qty": 100, "unit_price": 0.10},
    {"min_qty": 1000,"unit_price": 0.07}
  ],
  "dnp": false,
  "mpn": "RC0402FR-0710KL",
  "lead_time_weeks": 4,
  "num_sources": 2
}
```

**Output:**
```json
{
  "ok": true,
  "subtotal_parts_usd": 12.34,
  "nre_usd": 50.00,
  "total_usd": 62.34,
  "per_board_usd": 0.6234,
  "assembly_qty": 100,
  "board_qty": 100,
  "missing_price_lines": [],
  "dnp_lines": ["R5"],
  "line_items": [...]
}
```

---

## `bom_dfm_report`

Runs DFM rule checks on a CircuitJSON board per IPC-2221B / IPC-A-600K class thresholds.

**Board classes** (IPC-2221B §9):
- `1` — General/consumer electronics (least restrictive)
- `2` — Commercial/industrial (default)
- `3` — High-reliability: medical, aerospace (most restrictive)

**Rules checked:**

| Rule | Threshold source | Severity |
|------|-----------------|---------|
| Annular ring — via | IPC-2221B Table 9-1 (0.050 / 0.050 / 0.075 mm) | fail |
| Annular ring — PTH | IPC-2221B Table 9-1 (0.050 / 0.050 / 0.075 mm) | fail |
| Min trace width | IPC-2221B §9.1.1 (0.10 / 0.10 / 0.125 mm) | fail |
| Min trace space | IPC-2221B §9.1.1 (0.10 / 0.10 / 0.125 mm) | fail |
| Drill-to-copper | IPC-2221B §9.3.1 (0.20 / 0.25 / 0.33 mm) | fail |
| Silkscreen over pad | IPC-A-600K §3 | warn |
| Acid trap (sharp corner) | < 45° junction | warn |
| Copper sliver | short thin segment | warn |
| Courtyard overlap | IPC-7251 §3.1 / IPC-2221B §9.4 | fail |
| Smallest passive | IPC-7711/7721 §4.3 (0402 class 1/2; 0603 class 3) | warn |

**Output:**
```json
{
  "ok": true,
  "board_class": 2,
  "score": 85,
  "fail_count": 1,
  "warn_count": 0,
  "findings": [
    {
      "rule": "annular_ring_via",
      "severity": "fail",
      "message": "Via annular ring 0.020 mm < IPC minimum 0.050 mm",
      "location": "45.000,32.000"
    }
  ]
}
```

Score formula: `max(0, 100 − 15×fails − 5×warns)`.

---

## `bom_sourcing_risk`

Scans BOM lines for supply-chain risks without any live distributor calls.

**Flags:**
- `single_source` (fail) — `num_sources == 1`
- `no_price` (warn) — no `unit_price` and no `price_breaks`
- `long_lead` (warn) — `lead_time_weeks > long_lead_weeks` (default 16)

**Output:**
```json
{
  "ok": true,
  "risk_count": 2,
  "fail_count": 1,
  "warn_count": 1,
  "risks": [
    {
      "refdes": "U1",
      "risk": "single_source",
      "severity": "fail",
      "message": "U1 (ATMEGA328P-AU): single-source part — supply disruption has no alternative"
    }
  ]
}
```

---

## Combining the tools

Typical LLM workflow:
1. `bom_cost_rollup` — get extended cost, identify missing prices
2. `bom_sourcing_risk` — flag single-source / long-lead risks
3. `bom_dfm_report` — run DFM check on the circuit_json, get score

These tools complement the existing `variant_bom` / `variant_fab` tools in
`kerf_electronics.tools.variants` — they operate on the same BOM line-item
format and accept the same `dnp_list` / variant patterns.
