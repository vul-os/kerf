# Pressure Vessel Design (ASME BPVC VIII-1)

Pure-Python ASME BPVC Section VIII Division 1 pressure-vessel calculations. No
OCC dependency. All tools are stateless — they compute and return results; no
DB write. Units: SI (metres, Pascals gauge).

Reference: ASME BPVC Section VIII Division 1, 2021 Edition
(UG-27, UG-28, UG-32, UG-37, UG-99).

---

## When to use

Trigger on: pressure vessel, ASME VIII, BPVC, vessel shell thickness, head
thickness, hemispherical head, ellipsoidal head, 2:1 ellipsoidal, flanged and
dished, torispherical head, external pressure, vessel buckling, MAWP, maximum
allowable working pressure, nozzle reinforcement, area replacement, hydrostatic
test, vessel design pressure, corrosion allowance, joint efficiency, UG-27,
UG-28, UG-32, UG-37, UG-99.

---

## Tools

### `pv_cylindrical_shell_thickness`

Compute minimum wall thickness for a cylindrical shell under internal pressure
per ASME BPVC VIII-1 UG-27(c).

**Key inputs:** `P` (design pressure, Pa gauge), `R` (inside radius, m), `S`
(allowable stress, Pa). Optional: `E` (joint efficiency, default 1.0), `c`
(corrosion allowance, m, default 0).

**Computes:** t = P·R / (S·E − 0.6·P) + c (hoop stress governs);
longitudinal stress check also performed.

**Returns:** `t_required_m`, `t_required_mm`, intermediate values, warnings.

---

### `pv_spherical_head_thickness`

Compute wall thickness for a hemispherical head per UG-32(f).

**Key inputs:** `P`, `R` (inside radius, m), `S`. Optional: `E`, `c`.

**Computes:** t = P·R / (2·S·E − 0.2·P) + c.

**Returns:** `t_required_m`, `t_required_mm`.

---

### `pv_ellipsoidal_head_thickness`

Compute wall thickness for a standard 2:1 semi-ellipsoidal head per UG-32(d).

**Key inputs:** `P`, `D` (inside shell diameter, m), `S`. Optional: `E`, `c`.

**Computes:** t = P·D / (2·S·E − 0.2·P) + c.

**Returns:** `t_required_m`, `t_required_mm`.

---

### `pv_torispherical_head_thickness`

Compute wall thickness for a flanged-and-dished (torispherical) head per UG-32(e).

**Key inputs:** `P`, `D` (inside diameter, m), `S`. Optional: `E`, `c`,
`L_crown` (inside crown radius, m; default = D).

**Computes:** t = 0.885·P·L / (S·E − 0.1·P) + c.

**Returns:** `t_required_m`, `t_required_mm`.

---

### `pv_external_pressure_check`

Simplified UG-28 external pressure / buckling check for a cylindrical shell.

**Key inputs:** `P_ext` (external pressure, Pa), `D_o` (outside diameter, m),
`L` (unsupported length between stiffeners or heads, m), `t` (wall thickness,
m). Optional: `E_mod` (Pa, default 200e9), `nu` (default 0.3), `S_allow` (Pa).

**Computes:** factor A, factor B, allowable external pressure P_allow.
Returns pass/fail against P_ext.

**Returns:** `P_allow_Pa`, pass/fail, safety factor, warnings (flags short
vessels where L/D_o < 4).

---

### `pv_mawp_cylindrical`

Compute MAWP from a known cylindrical shell thickness per UG-27(c)(1).

**Key inputs:** `t` (nominal thickness, m), `R` (inside radius, m), `S`.
Optional: `E`, `c`.

**Computes:** MAWP = S·E·t_net / (R + 0.6·t_net) where t_net = t − c.

**Returns:** MAWP in Pa, kPa, bar, and psi.

---

### `pv_nozzle_reinforcement`

Check nozzle opening reinforcement per ASME BPVC VIII-1 UG-37 area-replacement.

**Key inputs:** `P`, `D_shell`, `t_shell`, `d_nozzle` (bore diameter, m),
`t_nozzle` (m), `S`. Optional: `E`, `c`, `F` (inclination factor, default 1.0).

**Computes:** A_required = d × t_req × F; A1 (excess shell), A2 (nozzle wall)
within reinforcement zone. Pass if A1 + A2 ≥ A_required.

**Returns:** `A_required_m2`, `A1_m2`, `A2_m2`, `A_total_m2`, pass/fail,
shortfall (if any).

---

### `pv_hydrostatic_test_pressure`

Compute required hydrostatic test pressure per ASME BPVC VIII-1 UG-99(b).

**Key inputs:** `MAWP` (Pa). Optional: `S_test` and `S_design` (Pa) for the
stress-ratio correction.

**Computes:** P_test = 1.3 × MAWP × (S_test / S_design).

**Returns:** `P_test_Pa`, `P_test_kPa`, `P_test_bar`, `P_test_psi`.

---

## Example

**User:** "Design a carbon steel pressure vessel shell: 600 mm inside diameter,
design pressure 1.5 MPa, allowable stress 138 MPa, full radiography (E=1.0),
3 mm corrosion allowance. What's the minimum wall thickness and MAWP?"

**Tools:**
1. `pv_cylindrical_shell_thickness` P:1.5e6 R:0.30 S:138e6 E:1.0 c:0.003
   → t_required_mm.
2. `pv_mawp_cylindrical` t:[nominal from stock] R:0.30 S:138e6 c:0.003
   → MAWP in bar and psi.
