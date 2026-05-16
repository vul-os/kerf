# Process Piping Design (ASME B31.3)

Pure-Python ASME B31.3 process piping calculations. No OCC dependency. All
tools are stateless — they compute and return results; no DB write.
Units: SI (metres, Pascals, kg/m³, m³/s, °C).

References: ASME B31.3-2022; ASME B36.10M-2018; Crane TP-410; MSS SP-69.

---

## When to use

Trigger on: pipe schedule, NPS, pipe wall thickness, B31.3, minimum wall,
pressure drop, Darcy-Weisbach, pipe friction, pipe flow, pipe support span,
hanger spacing, thermal expansion pipe, expansion loop, guided cantilever,
expansion stress, pipe flexibility, piping stress, process piping, pipe sizing,
pipe schedule 40, schedule 80, corrosion allowance, mill tolerance.

---

## Tools

### `pipe_schedule_lookup`

Look up pipe OD and wall thickness from ASME B36.10M / B36.19M tables.

**Key inputs:** `nominal_size_in` (NPS as string or number, e.g. `'4'`, `1.5`),
`schedule` (e.g. `'40'`, `'80'`, `'XXS'`).

**Returns:** OD, wall thickness, and ID in both mm and metres.

---

### `pipe_wall_thickness`

Compute minimum required wall thickness per ASME B31.3 §304.1.2 Eq. (3a).

**Key inputs:** `P` (design pressure, Pa), `D` (OD, m), `S` (allowable stress,
Pa). Optional: `E` (joint factor), `W` (weld reduction), `Y` (B31.3 coeff.),
`c_corr` (corrosion allowance, m), `c_mill` (mill tolerance fraction).

**Returns:** `t_required_m`, `t_required_mm`, and all intermediate values.

---

### `pipe_pressure_drop`

Compute single-phase Darcy-Weisbach pressure drop with Colebrook-White friction.

**Key inputs:** `Q` (m³/s), `rho` (kg/m³), `mu` (Pa·s), `D_i` (inside
diameter, m), `L` (length, m). Optional: `roughness` (m), `fittings_Le`
(equivalent fitting length, m).

**Returns:** `delta_P_Pa`, `delta_P_kPa`, `delta_P_bar`, velocity, Re, friction
factor. Warns if velocity > 3 m/s or Re is in transition zone.

---

### `pipe_allowable_span`

Compute maximum allowable pipe support span per MSS SP-69.

**Key inputs:** `D_o`, `D_i` (m), `rho_pipe`, `rho_fluid` (kg/m³), `E` (Pa),
`S_allow` (Pa). Optional: `deflection_limit` (m, default 0.0254 m = 1 inch).

**Returns:** `governing_span_m`, span from deflection criterion, span from
stress criterion, and section properties.

---

### `pipe_thermal_expansion`

Compute free thermal elongation of a pipe segment.

**Key inputs:** `L` (m), `alpha` (CTE, 1/°C; carbon steel ≈ 11.7e-6,
SS316 ≈ 16.0e-6), `T_install` (°C), `T_operating` (°C).

**Returns:** `delta_L_m`, `delta_L_mm`, `delta_T`.

---

### `pipe_guided_cantilever_leg`

Compute minimum leg length for a guided-cantilever expansion loop.

**Key inputs:** `D_o` (m), `t` (wall thickness, m), `E` (Pa), `S_allow`
(allowable expansion stress, Pa; typically S_A per B31.3), `delta`
(displacement to absorb, m).

**Returns:** `L_leg_min_m` and `L_leg_min_mm`.

---

### `pipe_expansion_stress`

Two-anchor expansion stress check via guided-cantilever method (ASME B31.3
Appendix D / Kellogg).

**Key inputs:** `delta_x`, `delta_y`, `delta_z` (displacements per direction,
m), `L_x`, `L_y` (absorbing leg lengths, m), `E` (Pa), `D_o` (m), `t` (m),
`S_allow` (Pa).

**Returns:** per-direction stresses, SRSS total expansion stress, pass/fail,
safety factor.

---

## Example

**User:** "What schedule 40 pipe wall do I need for a 4-inch carbon steel line
at 1500 kPa design pressure, allowable stress 138 MPa?"

**Tools:**
1. `pipe_schedule_lookup` nominal_size_in:'4' schedule:'40' → get OD.
2. `pipe_wall_thickness` P:1500000 D:0.1143 S:138e6 → t_required_mm.
