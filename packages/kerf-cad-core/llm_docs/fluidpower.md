# Hydraulic Fluid Power Circuit Sizing

Pure-Python hydraulic circuit sizing tools. No OCC dependency. All tools are
stateless — compute and return results; no DB write. Units: SI (N, m, Pa, W).

---

## When to use

Use these tools when the user asks about hydraulic systems, cylinders, pumps,
motors, accumulators, valves, hose/pipe sizing, reservoir volume, or thermal
balance of a hydraulic power unit.

Keywords: hydraulic, fluid power, cylinder, pump, motor, accumulator, valve,
Cv, Kv, line sizing, pressure drop, reservoir, HPU, thermal, hose, actuator,
hydraulic circuit, regenerative.

---

## Tools

### `fp_cylinder`

Extend/retract force and velocity for a hydraulic cylinder; optionally
computes regenerative (regen) extend mode.

**Input:**
- `bore_m`, `rod_m`, `pressure_Pa`, `flow_m3s` (all required)
- `regen` — boolean, enable regen mode (default false)

**Returns:** `F_extend_N`, `F_retract_N`, `v_extend_ms`, `v_retract_ms`,
`F_regen_N`, `v_regen_ms`, `A_bore_m2`, `A_rod_m2`, `warnings`

---

### `fp_pump`

Size a hydraulic pump: actual flow, input power, and input torque.

**Input:** `displacement_m3`, `rpm`, `vol_eff`, `overall_eff`, `pressure_Pa` (all required)

**Returns:** `Q_theoretical_m3s`, `Q_actual_m3s`, `P_hydraulic_W`, `P_input_W`,
`T_input_Nm`, `warnings`

---

### `fp_motor`

Hydraulic motor output torque and shaft speed from displacement and pressure.

**Input:** `displacement_m3`, `pressure_Pa`, `rpm` (required); `mech_eff` (default 0.92), `vol_eff` (default 0.95)

**Returns:** `T_theoretical_Nm`, `T_output_Nm`, `Q_actual_m3s`, `omega_rad_s`, `P_output_W`

---

### `fp_accumulator`

Size a gas-charged accumulator using Boyle (isothermal) or adiabatic law.

**Input:** `V_total_m3`, `P1_Pa` (pre-charge), `P2_Pa` (min working), `P3_Pa` (max) (all required); `process` enum `'isothermal'`/`'adiabatic'` (default isothermal)

**Returns:** `delta_V_m3`, `delta_V_L`, `precharge_ok`, `warnings`

---

### `fp_valve_cv`

Valve flow coefficient Cv (US) or Kv (metric ISO) from flow and pressure drop.

**Input:** `Q_m3s`, `delta_P_Pa`, `SG` (all required); `metric` boolean (default false)

**Returns:** `Cv`, `Kv`, plus unit-converted values

---

### `fp_line_pressure_drop`

Hydraulic line pressure drop via Hagen-Poiseuille (laminar) or Darcy-Weisbach
(turbulent, Swamee-Jain friction factor).

**Input:** `Q_m3s`, `rho`, `mu`, `D_i_m`, `L_m` (all required); `roughness_m`, `fittings_Le_m` (optional)

**Returns:** `velocity_ms`, `Re`, `regime`, `f_darcy`, `delta_P_Pa`, `delta_P_bar`

---

### `fp_line_size`

Recommend hydraulic bore from ISO/Parker velocity limits for service type.

**Input:** `Q_m3s` (required); `service` enum `'suction'`/`'return'`/`'pressure'` (default pressure); `fluid_rho`, `fluid_mu`

**Returns:** `D_min_m`, `D_min_mm`, `D_rec_m`, `D_rec_mm`, `regime_at_D_rec`

---

### `fp_reservoir`

Rule-of-thumb hydraulic reservoir volume: V = rule_factor × Q_per_minute.

**Input:** `pump_flow_m3s` (required); `rule_factor` (default 3.0)

**Returns:** `V_reservoir_m3`, `V_reservoir_L`, `pump_flow_Lmin`

---

### `fp_thermal_balance`

Steady-state heat load and thermal balance of a hydraulic power unit.

**Input:** `input_power_W`, `eff_overall` (required); optional `area_m2`, `U_Wm2K`, `dT_K`, `cooling_flow_m3s`, `fluid_cp`, `fluid_rho`

**Returns:** `Q_heat_W`, `Q_surface_W`, `Q_cooler_W`, `thermal_balanced`, `heat_surplus_W`

---

## Example

```
1. fp_pump  displacement_m3:16e-6  rpm:1450  vol_eff:0.95
            overall_eff:0.88  pressure_Pa:14e6
   → Q_actual_m3s: 2.204e-4  P_input_W: 3521  T_input_Nm: 23.2

2. fp_cylinder  bore_m:0.063  rod_m:0.040  pressure_Pa:14e6
                flow_m3s:2.2e-4
   → F_extend_N: 43867  v_extend_ms: 0.070

3. fp_line_size  Q_m3s:2.2e-4  service:"pressure"
   → D_rec_mm: 9.7  (select 10 mm ID tubing)

4. fp_reservoir  pump_flow_m3s:2.2e-4
   → V_reservoir_L: 39.6  (select 40 L tank)
```
