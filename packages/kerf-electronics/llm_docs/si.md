# Signal Integrity (SI) Analyzer

Tools for controlled-impedance analysis, propagation delay, crosstalk
estimation, and termination recommendation for PCB nets.

---

## Tools

### `si_impedance`
Calculate single-ended Z0 and (optionally) differential Zdiff for a stackup
geometry.

**Input**
```json
{
  "structure": "microstrip" | "stripline",
  "trace_width_mm": 0.127,
  "dielectric_height_mm": 0.1,
  "copper_thickness_mm": 0.035,
  "er": 4.3,
  "spacing_mm": 0.15          // optional — enables Zdiff output
}
```

**Output**  `{ z0_ohms, zdiff_ohms?, formulas, ... }`

- `dielectric_height_mm` = H above ground plane (microstrip) or total B between
  reference planes (stripline).
- Default `copper_thickness_mm` = 0.035 mm (1 oz copper).
- Formulas: IPC-2141A (2004) for Z0; Wadell §3.7/4.3 for Zdiff.

---

### `si_propagation`
Propagation delay (ps/mm) and one-way flight time (ps).

**Input**
```json
{
  "er": 4.3,
  "length_mm": 100,
  "structure": "stripline",     // default stripline
  "trace_width_mm": 0.15,       // needed for microstrip er_eff
  "dielectric_height_mm": 0.1   // needed for microstrip er_eff
}
```

**Output**  `{ td_ps_per_mm, flight_time_ps, flight_time_ns }`

Typical FR4 stripline: ~6.9 ps/mm.  Microstrip er_eff < er → faster.

---

### `si_crosstalk`
First-order NEXT and FEXT estimate for an aggressor/victim trace pair.

**Input**
```json
{
  "spacing_mm": 0.2,
  "dielectric_height_mm": 0.15,
  "parallel_length_mm": 50,
  "er": 4.3,
  "structure": "microstrip",
  "aggressor_swing_mv": 1000
}
```

**Output**  `{ NEXT: { Kb, next_mv, next_pct }, FEXT: { Kf, fext_mv, fext_pct } }`

- NEXT and FEXT both decrease monotonically as `spacing_mm` increases.
- Stripline FEXT is ~10x lower than microstrip (inductive/capacitive cancellation).
- This is a pre-layout screening estimate; use a field solver for final signoff.

---

### `si_termination`
Reflection coefficient and recommended termination scheme.

**Input**
```json
{
  "driver_z_ohms": 25,
  "line_z0_ohms": 50,
  "topology": "point_to_point" | "bus" | "clock",
  "vcc_mv": 3300
}
```

**Output**  `{ scheme, description, resistor_ohms, gamma_open_load, gamma_at_driver, ... }`

| topology        | preferred scheme    | component            |
|-----------------|---------------------|----------------------|
| point_to_point  | series              | R_s = Z0 − R_driver  |
| bus             | Thevenin            | R1 = R2 = 2 × Z0     |
| clock           | AC (RC)             | R = Z0, C = 47–100 pF |
| matched         | none                | —                    |

---

### `si_report`
Combined per-net SI summary in one call.  Includes Z0, Zdiff (if spacing
given), propagation delay, flight time, crosstalk (if spacing + aggressor
run length given), and termination recommendation.

**Input**  (superset of all individual tool inputs)
```json
{
  "structure": "microstrip",
  "trace_width_mm": 0.127,
  "dielectric_height_mm": 0.1,
  "er": 4.3,
  "length_mm": 100,
  "driver_z_ohms": 25,
  "copper_thickness_mm": 0.035,
  "topology": "point_to_point",
  "spacing_mm": 0.2,
  "aggressor_parallel_length_mm": 50,
  "aggressor_swing_mv": 1000
}
```

---

## Relationship to `diffpair` tools

`calc_impedance` (in `diffpair`) and `si_impedance` use the same IPC-2141A
formulas; prefer `si_impedance` when you need propagation delay, crosstalk,
or termination in the same workflow.  Use `calc_impedance` / `add_diff_pair` /
`route_diff_pair` when physically routing a differential pair on a board.

---

## Formula references

- **IPC-2141A** (2004 edition): Controlled Impedance Circuit Boards and High
  Speed Logic Design — equations 1-1 (microstrip narrow), 1-2 (microstrip wide),
  2-1 (stripline symmetric buried).
- **Wadell, B. C.** "Transmission Line Design Handbook", Artech House (1991),
  §3.7 (microstrip differential) and §4.3 (stripline differential).
- **Hammerstad, E. O.** (1975): wide-trace effective permittivity correction.
