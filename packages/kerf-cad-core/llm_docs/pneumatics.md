# Pneumatic Circuit Sizing (ISO 6358)

Pure-Python pneumatic circuit sizing tools. No OCC dependency. All tools are
stateless — compute and return results; no DB write. Units: SI (Pa absolute,
m, m³/s, Nl/min).

---

## When to use

Use these tools when the user asks about pneumatic actuators, air cylinders,
compressed air, pneumatic valves (ISO 6358, Cv), air receivers, compressors,
FRL units, charge/blowdown times, or free-air consumption.

Keywords: pneumatic, compressed air, cylinder, actuator, air valve, Cv, ISO 6358,
sonic conductance, receiver, compressor, FRL, filter regulator lubricator,
blowdown, charge time, free-air consumption, Nl/min, back pressure, choked flow.

---

## Tools

### `pneu_cylinder`

Pneumatic cylinder theoretical and effective extend/retract forces with load ratio.

All pressures are ABSOLUTE (Pa). Supply must be > 101325 Pa.

**Input:** `bore_m`, `rod_m`, `supply_pressure_Pa` (required); `load_N` (default 0), `friction_ratio` (default 0.05), `back_pressure_Pa` (default 101325)

**Returns:** `F_extend_th_N`, `F_retract_th_N`, `F_extend_eff_N`, `F_retract_eff_N`,
`load_ratio`, warnings if load ratio > 0.70

---

### `pneu_air_consumption`

Free-air consumption of a pneumatic cylinder per cycle (Nl/min).

**Input:** `bore_m`, `rod_m`, `stroke_m`, `supply_pressure_Pa`, `cycles_per_min` (all required); `double_acting` (default true), `T_K` (default 293.15)

**Returns:** `Q_free_Nl_min`, `V_free_m3_per_cycle`, `compression_ratio`

---

### `pneu_valve_iso6358`

Volumetric flow through a pneumatic valve per ISO 6358 (choked/subsonic).

q_max = C·P1·√(T_N/T1);  subsonic corrected for P2/P1.

**Input:** `P1_Pa`, `P2_Pa`, `T1_K`, `C_m3s_Pa` (sonic conductance), `b` (critical pressure ratio) — all required

**Returns:** `q_m3s_normal`, `q_Nl_min`, `choked` flag

---

### `pneu_valve_cv`

Volumetric flow through a pneumatic valve using US Cv coefficient (compressible).

**Input:** `Cv`, `P1_Pa`, `P2_Pa`, `T_K` (all required); `SG_gas` (default 1.0)

**Returns:** `q_Nl_min`, `q_m3s_normal`, `q_max_Nl_min`, `choked` flag

---

### `pneu_receiver_sizing`

Receiver hold-up time and free-air storage between cut-in and cut-out pressures.

**Input:** `V_receiver_m3`, `P_high_Pa`, `P_low_Pa`, `Q_demand_m3s_free` (all required); `T_K` (default 293.15)

**Returns:** `delta_V_free_m3`, `t_supply_s`, warnings if hold-up < 5 s

---

### `pneu_blowdown_time`

Time to exhaust a receiver to atmosphere through an ISO 6358 orifice/valve.

**Input:** `V_m3`, `P_initial_Pa`, `P_final_Pa`, `C_m3s_Pa`, `b` (all required); `T_K`

**Returns:** `t_blowdown_s`, `t_choked_s`, `t_subsonic_s`, warnings for rapid depressurisation

---

### `pneu_charge_time`

Time to charge a pneumatic receiver from a compressor (isothermal).

**Input:** `V_m3`, `P_initial_Pa`, `P_final_Pa`, `Q_compressor_m3s_free` (all required); `T_K`

**Returns:** `t_charge_s`, `delta_V_free_m3`, warning if charge time > 10 min

---

### `pneu_frl_drop`

Total pressure drop across an FRL unit (filter + regulator + lubricator).

**Input:** `Q_free_m3s`, `supply_pressure_Pa` (required); `filter_dP_Pa` (default 10000), `regulator_dP_Pa` (default 20000), `lubricator_dP_Pa` (default 10000)

**Returns:** `P_outlet_Pa`, `total_dP_Pa`, `frl_efficiency`, warnings if efficiency < 85%

---

## Example

```
1. pneu_cylinder  bore_m:0.050  rod_m:0.020
                  supply_pressure_Pa:700000  load_N:1200
   → F_extend_eff_N: 1601  load_ratio: 0.75 (WARN: oversized load)

2. pneu_air_consumption  bore_m:0.050  rod_m:0.020  stroke_m:0.200
                         supply_pressure_Pa:700000  cycles_per_min:10
   → Q_free_Nl_min: 89.4

3. pneu_receiver_sizing  V_receiver_m3:0.050
                         P_high_Pa:800000  P_low_Pa:600000
                         Q_demand_m3s_free:1.49e-3
   → t_supply_s: 18.7  (sufficient hold-up)
```
