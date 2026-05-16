# HVAC Duct Sizing

Pure-Python HVAC duct design calculations per ASHRAE Fundamentals Chapter 21.
No OCC dependency. All tools are stateless — they compute and return results;
no DB write. Units: US customary (CFM, fpm, in. w.g., BTU/h, °F, inches) with
Pa conversions where applicable.

References: ASHRAE Handbook — Fundamentals (2021), Ch. 21; Huebscher (1948).

---

## When to use

Trigger on: HVAC duct, duct sizing, airflow CFM, round duct, rectangular duct,
equivalent diameter, duct friction loss, duct pressure drop, duct fitting,
equal friction method, velocity reduction method, static pressure, fan law,
fan affinity law, supply air, return air, sensible load, BTU/h cooling,
heating load airflow, duct design, ASHRAE duct.

---

## Tools

### `hvac_cfm_from_sensible_load`

Calculate required airflow (CFM) from a sensible heating or cooling load.

**Key inputs:** `Q_btuh` (BTU/h), `delta_T_F` (supply-air temperature
differential, °F; typical 20°F cooling, 50°F heating).

**Returns:** `cfm`.

---

### `hvac_round_duct_diameter`

Calculate round duct diameter from airflow and target velocity.

**Key inputs:** `cfm`, `velocity_fpm`.

**Returns:** `diameter_in`. Warns when velocity exceeds ASHRAE guidelines
(> 800 fpm branch, > 1500 fpm main trunk).

---

### `hvac_rect_equiv_diameter`

Compute Huebscher equivalent diameter for a rectangular duct.

**Key inputs:** `a_in` (width, inches), `b_in` (height, inches).

**Returns:** `D_e_in` (equivalent round diameter). Warns when aspect ratio > 4:1.

---

### `hvac_duct_friction_loss`

Calculate Darcy-Weisbach friction pressure loss for a straight round duct.

**Key inputs:** `cfm`, `diameter_in`, `length_ft`. Optional: `roughness_ft`
(default 0.00015 ft for sheet metal).

**Returns:** `loss_in_wg`, `loss_Pa`, `friction_rate_in_per_100ft`, velocity,
Reynolds number.

---

### `hvac_duct_fitting_loss`

Calculate dynamic pressure loss for a single duct fitting.

**Key inputs:** `cfm`, `diameter_in`, `C` (loss coefficient, dimensionless;
e.g. 0.22 for 90° elbow r=1.5D).

**Returns:** `loss_in_wg`, `loss_Pa`, velocity, dynamic pressure.

---

### `hvac_size_equal_friction`

Size a round duct by the equal-friction method.

**Key inputs:** `cfm`, `friction_rate_in_per_100ft` (target friction rate;
0.08–0.10 low-velocity, 0.10–0.15 medium-velocity). Optional: `roughness_ft`.

**Returns:** `diameter_in`, resulting velocity, friction rate confirmation.

---

### `hvac_size_velocity_reduction`

Size a duct system by the velocity-reduction method.

**Key inputs:** `cfm_list` (list of CFM per section), `velocity_fpm_list`
(target velocity per section; decreasing trunk to branch, e.g. [1200, 900, 700]).

**Returns:** list of `{diameter_in, velocity_fpm}` per section.

---

### `hvac_branch_static_pressure`

Calculate total static pressure for a duct branch path from fan to terminal.

**Key inputs:** `sections` — list of `{cfm, diameter_in, length_ft, fittings:[{C}]}`.

**Returns:** `total_static_pressure_in_wg`, `total_static_pressure_Pa`, and
per-section breakdown of friction + fitting losses.

---

### `hvac_fan_law_scale`

Scale fan performance to a new airflow using affinity laws.

**Key inputs:** `cfm1`, `sp1` (in. w.g.), `bhp1` (BHP), `cfm2`.

**Computes:** SP₂ = SP₁ × (CFM₂/CFM₁)², BHP₂ = BHP₁ × (CFM₂/CFM₁)³.

**Returns:** `cfm2`, `sp2_in_wg`, `bhp2`. Warns when speed ratio > 1.2 or < 0.5.

---

## Example

**User:** "I have a 36 000 BTU/h sensible cooling load with a 20°F temperature
differential. Size the main trunk duct at 1200 fpm and find its friction loss
over 50 feet."

**Tools:**
1. `hvac_cfm_from_sensible_load` Q_btuh:36000 delta_T_F:20 → 1667 CFM.
2. `hvac_round_duct_diameter` cfm:1667 velocity_fpm:1200 → diameter_in.
3. `hvac_duct_friction_loss` cfm:1667 diameter_in:[result] length_ft:50 → loss.
