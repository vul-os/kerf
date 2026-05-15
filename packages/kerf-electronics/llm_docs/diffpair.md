# Differential Pairs, Controlled Impedance, and Matched-Length Groups

KiCad-parity tools for differential-pair routing, controlled-impedance trace sizing,
and matched-length group management.

---

## Data model

### `board.differential_pairs`

Defines P/N pairs.  Read by both `diffpair` and `length_tuning` tools.

```jsonc
{
  "type": "pcb_board",
  "differential_pairs": [
    {
      "name": "USB_DP",
      "net_p_id": "USB_P",
      "net_n_id": "USB_N",
      "spacing_mm": 0.2,
      "width_mm": 0.15,
      "skew_max_mm": 0.05,
      "target_impedance_ohms": 90   // optional, informational
    }
  ]
}
```

### `board.diff_pair_routes`

Added by `route_diff_pair` to record which traces belong to each routed pair.

```jsonc
"diff_pair_routes": [
  {
    "pair_name": "USB_DP",
    "trace_p_id": "dp_p_a1b2c3d4",
    "trace_n_id": "dp_n_e5f6a7b8",
    "layer": "top_copper",
    "spacing_mm": 0.2,
    "width_mm": 0.15
  }
]
```

### `board.length_groups`

Matched-length group definitions consumed by `check_length_match`.

```jsonc
"length_groups": [
  {
    "name": "DDR_DQ_BYTE0",
    "net_ids": ["DQ0", "DQ1", "DQ2", "DQ3", "DQS_P", "DQS_N"],
    "target_length_mm": 72.0,
    "skew_max_mm": 0.1,
    "serpentine_amplitude_mm": 0.5
  }
]
```

---

## Impedance formulas

All calculations are pure-Python closed-form approximations — no simulation.

### Microstrip (surface trace above ground plane)

**Single-ended Z0** — IPC-2141A (2004) / Hammerstad (1975):

- **Narrow trace** (W/H ≤ 1):
  `Z0 = (87 / √(εr + 1.41)) × ln(5.98·H / (0.8·W + T))`

- **Wide trace** (W/H > 1):
  Effective permittivity: `εr_eff = (εr+1)/2 + (εr−1)/2 × (1 + 12·H/W)^−0.5`
  `Z0 = 120π / (√εr_eff × (W/H + 1.393 + 0.667·ln(W/H + 1.444)))`

A thickness correction `We = W + (T/π)×(1 + ln(2H/T))` is applied before substituting W.

**Reference 50 Ω FR4 stackup (verified):**
W = 0.32 mm, H = 0.2 mm, T = 0.035 mm (1 oz), εr = 4.5 → Z0 ≈ 51.7 Ω

### Stripline (buried trace between two reference planes)

**Single-ended Z0** — IPC-2141A symmetric buried stripline:
`Z0 = (60 / √εr) × ln(4·B / (0.67·π·(0.8·W + T)))`

where B = total dielectric thickness between the two reference planes.

**Reference 50 Ω FR4 stackup (verified):**
W = 0.1 mm, B = 0.36 mm, T = 0.035 mm, εr = 4.5 → Z0 ≈ 50.4 Ω

### Differential impedance (microstrip and stripline)

**Zdiff** — Wadell, *Transmission Line Design Handbook* (Artech House, 1991), §3.7 (microstrip) / §4.3 (stripline):

`Zdiff = 2 × Z0 × (1 − 0.347 × exp(−2.9 × S / H))`

where S = edge-to-edge gap between P and N traces, H = dielectric height (microstrip) or B (stripline).

At large S/H the exponential → 0 and Zdiff → 2·Z0. At tight coupling the factor reduces Zdiff.

**Reference 100 Ω diff pair FR4 stackup (verified):**
W = 0.32 mm, H = 0.2 mm, S = 0.5 mm, T = 0.035 mm, εr = 4.5 → Zdiff ≈ 103 Ω

---

## Tools

### `add_diff_pair`

Define (or update) a differential pair.  Writes to `board.differential_pairs`.

```json
{
  "circuit_json": [...],
  "name": "USB_DP",
  "net_p_id": "USB_P",
  "net_n_id": "USB_N",
  "spacing_mm": 0.2,
  "width_mm": 0.15,
  "skew_max_mm": 0.05,
  "target_impedance_ohms": 90
}
```

Returns `{ "circuit_json": [...], "pair": { ... } }`.

---

### `route_diff_pair`

Route a defined differential pair along a centreline path.  The P trace is
offset `+spacing/2` and the N trace `−spacing/2` (CCW perpendicular).  Appends
two `pcb_trace` elements and a record in `board.diff_pair_routes`.

```json
{
  "circuit_json": [...],
  "pair_name": "USB_DP",
  "centreline": [
    { "x": 10, "y": 20 },
    { "x": 50, "y": 20 },
    { "x": 50, "y": 60 }
  ],
  "layer": "top_copper"
}
```

Returns `{ "circuit_json", "trace_p_id", "trace_n_id", "length_p_mm", "length_n_mm", "skew_mm" }`.

**Skew**: For straight segments skew is exactly zero.  At bends the outer trace
is slightly longer; use `match_diff_pair` (from `length_tuning`) to correct.

---

### `calc_impedance`

Calculate single-ended Z0 and (optionally) differential Zdiff for a given stackup.

```json
{
  "structure": "microstrip",
  "trace_width_mm": 0.32,
  "dielectric_height_mm": 0.2,
  "copper_thickness_mm": 0.035,
  "er": 4.5,
  "spacing_mm": 0.5
}
```

Returns:
```json
{
  "structure": "microstrip",
  "z0_ohms": 51.68,
  "zdiff_ohms": 103.33,
  "formulas": "Z0: IPC-2141A (2004); Zdiff: Wadell ... (1991) §3.7/4.3"
}
```

`spacing_mm` is optional; omit it to get only Z0.

**Typical FR4 stackups:**

| Structure  | Target Z0  | W (mm) | H / B (mm) | T (mm) | εr  |
|------------|-----------|--------|------------|--------|-----|
| Microstrip | 50 Ω      | 0.32   | 0.20       | 0.035  | 4.5 |
| Stripline  | 50 Ω      | 0.10   | 0.36       | 0.035  | 4.5 |
| Microstrip | ~100 Ω diff | 0.32 | 0.20      | 0.035  | 4.5 (S=0.5 mm) |

---

### `add_length_group`

Define a matched-length group.  All listed nets must reach `target_length_mm`
within `skew_max_mm`.

```json
{
  "circuit_json": [...],
  "name": "DDR_DQ_BYTE0",
  "net_ids": ["DQ0", "DQ1", "DQ2", "DQ3"],
  "target_length_mm": 72.0,
  "skew_max_mm": 0.1,
  "serpentine_amplitude_mm": 0.5
}
```

Returns `{ "circuit_json": [...], "group": { ... } }`.

---

### `check_length_match`

Report each net's current routed length vs target and the serpentine delta needed.

```json
{
  "circuit_json": [...],
  "group_name": "DDR_DQ_BYTE0"
}
```

Returns:
```json
{
  "group_name": "DDR_DQ_BYTE0",
  "target_length_mm": 72.0,
  "skew_max_mm": 0.1,
  "all_pass": false,
  "nets": [
    {
      "net_id": "DQ0",
      "current_length_mm": 60.0,
      "target_length_mm": 72.0,
      "delta_mm": 12.0,
      "needs_tuning": true,
      "recommended_serpentine_delta_mm": 12.0,
      "recommended_amplitude_mm": 0.5
    },
    {
      "net_id": "DQ1",
      "current_length_mm": 72.0,
      "delta_mm": 0.0,
      "needs_tuning": false,
      "recommended_serpentine_delta_mm": 0.0,
      "recommended_amplitude_mm": null
    }
  ]
}
```

After `check_length_match`, call `set_trace_target_length` + `tune_trace_to_target`
(from `length_tuning`) on each net where `needs_tuning = true`.

---

## Typical workflows

### Define and route a USB 2.0 diff pair

```
1. add_diff_pair  — name="USB_DP", net_p_id="USB_P", net_n_id="USB_N",
                    spacing_mm=0.2, width_mm=0.15, skew_max_mm=0.05
2. calc_impedance — structure="microstrip", trace_width_mm=0.15,
                    dielectric_height_mm=0.2, er=4.5, spacing_mm=0.2
                    → check zdiff_ohms ≈ 90 Ω (USB 2.0 spec)
3. route_diff_pair — pair_name="USB_DP", centreline=[...]
4. report_diff_pair_skew — pair_name="USB_DP"
5. match_diff_pair  — pair_name="USB_DP"  (if skew > 0.05 mm)
```

### Match a DDR4 byte lane

```
1. add_length_group — name="DQ_B0", net_ids=["DQ0".."DQ7","DQS_P","DQS_N"],
                      target_length_mm=72.0, skew_max_mm=0.1
2. check_length_match — group_name="DQ_B0"
3. For each net where needs_tuning=true:
   set_trace_target_length + tune_trace_to_target  (from length_tuning)
4. check_length_match — group_name="DQ_B0"  (verify all_pass=true)
```

### Size a 50 Ω controlled-impedance trace

```
calc_impedance — structure="microstrip", trace_width_mm=0.32,
                 dielectric_height_mm=0.2, copper_thickness_mm=0.035, er=4.5
→ z0_ohms ≈ 51.7 Ω
```

Adjust `trace_width_mm` or `dielectric_height_mm` until `z0_ohms` is within
your tolerance, then set that width when routing with `route_trace_segments`.
