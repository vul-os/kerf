# PDN (Power Distribution Network) Analysis

Pure-Python DC IR-drop solver, target-impedance estimator, and decoupling-cap
count estimator for power integrity analysis on PCB designs.

---

## Overview

Three tools:

| Tool | Purpose |
|---|---|
| `pdn_ir_drop` | DC IR-drop analysis — node voltages + pass/fail |
| `pdn_target_impedance` | Zt formula + first-order decap count |
| `pdn_report` | Combined IR-drop + target-impedance in one call |

All tools are pure-Python (no numpy/scipy). Results are deterministic and
hermetic — no board file I/O is performed.

---

## Data model

### Nodes

```jsonc
{
  "node_id": "VDD",        // unique string identifier
  "is_source": true,       // exactly one node per network must be true
  "voltage_v": 3.3,        // required on source node
  "i_draw_a": 0.0          // current drawn at this node (A); 0 = intermediate
}
```

### Segments (resistive conductors)

```jsonc
// Option A — explicit resistance:
{ "node_a": "VDD", "node_b": "U1_VDD", "resistance_ohms": 0.005 }

// Option B — copper geometry + pre-computed sheet resistance:
{ "node_a": "VDD", "node_b": "U1_VDD",
  "length_mm": 20, "width_mm": 2,
  "sheet_resistance_ohms_per_sq": 4.926e-4 }   // 1 oz copper

// Option C — copper geometry + copper weight (tool computes sheet R):
{ "node_a": "VDD", "node_b": "U1_VDD",
  "length_mm": 20, "width_mm": 2,
  "copper_weight_oz": 1.0 }
```

### Embedding in `circuit_json`

If you have a CircuitJSON board object, store PDN data in:
- `board.pdn_nodes`    — list of node dicts
- `board.pdn_segments` — list of segment dicts

The tools will read these automatically when `nodes`/`segments` are not
supplied inline.

---

## Copper sheet resistance reference

| Copper weight | Thickness | Sheet R (Ω/sq) |
|---|---|---|
| 0.5 oz | 17.5 µm | ≈ 0.985 mΩ/sq |
| 1 oz   | 35 µm   | ≈ 0.493 mΩ/sq |
| 2 oz   | 70 µm   | ≈ 0.246 mΩ/sq |
| 3 oz   | 105 µm  | ≈ 0.164 mΩ/sq |

Formula: `Rsheet = ρ_Cu / t`  where ρ_Cu = 1.724×10⁻⁸ Ω·m at 20 °C.

---

## Tools

### `pdn_ir_drop`

DC IR-drop analysis using modified nodal analysis (conductance matrix, Gauss–Jordan).

```json
{
  "nodes": [
    { "node_id": "VDD",  "is_source": true, "voltage_v": 3.3 },
    { "node_id": "U1",   "i_draw_a": 0.5 },
    { "node_id": "U2",   "i_draw_a": 0.3 }
  ],
  "segments": [
    { "node_a": "VDD", "node_b": "U1",
      "length_mm": 15, "width_mm": 1.5, "copper_weight_oz": 1.0 },
    { "node_a": "VDD", "node_b": "U2",
      "length_mm": 30, "width_mm": 1.0, "copper_weight_oz": 1.0 }
  ],
  "ir_drop_budget_v": 0.05
}
```

Returns:
```json
{
  "ok": true,
  "source_node_id": "VDD",
  "source_voltage_v": 3.3,
  "all_node_voltages": { "VDD": 3.3, "U1": 3.295, "U2": 3.285 },
  "sinks": [
    { "node_id": "U1", "voltage_v": 3.295, "ir_drop_v": 0.005,
      "current_a": 0.5, "pass_fail": "PASS", "budget_v": 0.05 },
    { "node_id": "U2", "voltage_v": 3.285, "ir_drop_v": 0.015,
      "current_a": 0.3, "pass_fail": "PASS", "budget_v": 0.05 }
  ],
  "worst_ir_drop_v": 0.015,
  "worst_node_id": "U2",
  "all_pass": true,
  "total_current_a": 0.8
}
```

`pass_fail` values:
- `"PASS"` — IR drop ≤ `ir_drop_budget_v`
- `"FAIL"` — IR drop > `ir_drop_budget_v`
- `"UNSPEC"` — no budget supplied

---

### `pdn_target_impedance`

Target impedance formula + first-order decap count estimate.

```json
{
  "vdd_v": 3.3,
  "ripple_fraction": 0.05,
  "i_transient_a": 2.0,
  "cap_value_f": 1e-7,
  "cap_esl_h": 1e-9,
  "frequency_hz": 1e8
}
```

Returns:
```json
{
  "ok": true,
  "vdd_v": 3.3,
  "ripple_fraction": 0.05,
  "i_transient_a": 2.0,
  "target_impedance_ohms": 0.0825,
  "decap": {
    "count": 2,
    "z_single_ohms": 0.142,
    "srf_hz": 15915494.3,
    "regime": "capacitive",
    "target_impedance_ohms": 0.0825,
    "cap_value_f": 1e-7,
    "cap_esl_h": 1e-9,
    "frequency_hz": 1e8
  }
}
```

**Formulas:**

- Target impedance: `Zt = (Vdd × ripple_fraction) / I_transient`
- Cap impedance at frequency: `|Z| = |Xc − Xl| = |1/(ωC) − ωL|`
- Caps needed: `N = ceil(|Z_single| / Zt)`
- SRF: `f_srf = 1 / (2π √(L·C))`

The model ignores ESR (conservative). Above SRF the cap is inductive — more
caps are needed or a different (smaller) cap value should be used.

---

### `pdn_report`

Combined call. Either section may be omitted.

```json
{
  "nodes": [...],
  "segments": [...],
  "ir_drop_budget_v": 0.05,
  "vdd_v": 3.3,
  "ripple_fraction": 0.05,
  "i_transient_a": 2.0,
  "cap_value_f": 1e-7,
  "cap_esl_h": 1e-9,
  "frequency_hz": 1e8
}
```

Returns `{ "ok": true, "ir_drop": {...}, "target_impedance": {...} }`.

---

## Typical workflows

### Check 3.3 V rail for a new design

```
1. Identify power net topology: source decap → trace → FPGA, MCU, etc.
2. pdn_ir_drop:
     nodes = [VDD(source, 3.3V), FPGA(0.8A), MCU(0.3A)]
     segments = [VDD→FPGA (20mm × 1.5mm, 1oz), VDD→MCU (50mm × 1mm, 1oz)]
     ir_drop_budget_v = 0.05   // 5% of 3.3V = 165 mV; use tighter 50 mV
3. If all_pass=false, widen traces or add copper pours.
```

### Size the decap bank for a 1.8 V DDR4 rail

```
1. Determine worst-case transient: I_transient = 8 A (DDR4 burst)
2. Ripple spec: ±3% → ripple_fraction = 0.03
3. pdn_target_impedance:
     vdd_v=1.8, ripple_fraction=0.03, i_transient_a=8
     cap_value_f=100e-9, cap_esl_h=0.5e-9, frequency_hz=200e6
4. Read decap.count — add that many 100 nF caps to the VDD plane.
5. If regime="inductive" at your target frequency, switch to a smaller cap
   (e.g. 10 nF) with lower ESL, then re-run.
```

### Trace resistance quick-check

```
pdn_ir_drop with a two-node net (VDD → LOAD) and a single segment specified
by copper geometry → instant Ohm's law check without modelling the full board.
```

---

## Limitations

- **DC only** — no frequency-domain impedance of planes/vias.
- **Lumped resistors** — planes are approximated as trace segments; use
  finer meshes for large solid pours.
- **No ESR** in decap model (conservative count).
- **No thermal** resistance correction (room-temperature copper assumed).
