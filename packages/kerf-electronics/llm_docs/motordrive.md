# motordrive

*Module: `kerf_electronics.motordrive.tools` · Domain: electronics*

This module registers **12** LLM tool(s):

- [`motordrive_load_torque_power`](#motordrive-load-torque-power)
- [`motordrive_reflected_inertia`](#motordrive-reflected-inertia)
- [`motordrive_inertia_match`](#motordrive-inertia-match)
- [`motordrive_rms_torque`](#motordrive-rms-torque)
- [`motordrive_motor_constants`](#motordrive-motor-constants)
- [`motordrive_dc_operating_point`](#motordrive-dc-operating-point)
- [`motordrive_bldc_pmsm_op_point`](#motordrive-bldc-pmsm-op-point)
- [`motordrive_induction_slip_torque`](#motordrive-induction-slip-torque)
- [`motordrive_inverter_sizing`](#motordrive-inverter-sizing)
- [`motordrive_regen_energy`](#motordrive-regen-energy)
- [`motordrive_brake_resistor`](#motordrive-brake-resistor)
- [`motordrive_thermal_duty`](#motordrive-thermal-duty)

---

## `motordrive_load_torque_power`

Compute total shaft torque and mechanical power required from a motor.

Total torque: T = T_load + J×α + T_friction + B×ω
Mechanical power: P = T_total × ω

Input: { speed_rpm, torque_load_nm, inertia_kgm2?, accel_rad_s2?, friction_nm?, viscous_nm_per_rad_s? }
Returns: { ok, omega_rad_s, t_total_nm, t_inertial_nm, t_friction_nm, t_viscous_nm, p_mech_w, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "speed_rpm": {
      "type": "number",
      "description": "Shaft speed [RPM]."
    },
    "torque_load_nm": {
      "type": "number",
      "description": "Load (useful output) torque [N\u00b7m]."
    },
    "inertia_kgm2": {
      "type": "number",
      "description": "Total reflected inertia [kg\u00b7m\u00b2] (default 0)."
    },
    "accel_rad_s2": {
      "type": "number",
      "description": "Angular acceleration [rad/s\u00b2] (default 0)."
    },
    "friction_nm": {
      "type": "number",
      "description": "Constant friction torque [N\u00b7m] (default 0)."
    },
    "viscous_nm_per_rad_s": {
      "type": "number",
      "description": "Viscous damping coefficient [N\u00b7m\u00b7s/rad] (default 0)."
    }
  },
  "required": [
    "speed_rpm",
    "torque_load_nm"
  ]
}
```

---

## `motordrive_reflected_inertia`

Reflect load-side inertia to the motor shaft through a gearbox.

J_reflected = J_load / (N² × η_gb)

Input: { j_load_kgm2, gear_ratio, gearbox_efficiency? }
Returns: { ok, j_reflected_kgm2, gear_ratio, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "j_load_kgm2": {
      "type": "number",
      "description": "Load-side inertia [kg\u00b7m\u00b2]."
    },
    "gear_ratio": {
      "type": "number",
      "description": "Gear ratio N = \u03c9_motor / \u03c9_load."
    },
    "gearbox_efficiency": {
      "type": "number",
      "description": "Gearbox mechanical efficiency (0, 1] (default 1.0)."
    }
  },
  "required": [
    "j_load_kgm2",
    "gear_ratio"
  ]
}
```

---

## `motordrive_inertia_match`

Compute load-to-motor inertia mismatch ratio and optimal gear ratio for inertia matching.

N_opt = sqrt(J_load / J_motor)
mismatch = J_load / (N² × J_motor)

A warning is issued when mismatch > mismatch_threshold (default 10).

Input: { j_motor_kgm2, j_load_kgm2, gear_ratio?, mismatch_threshold? }
Returns: { ok, mismatch_ratio, n_opt, inertia_matched, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "j_motor_kgm2": {
      "type": "number",
      "description": "Motor rotor inertia [kg\u00b7m\u00b2]."
    },
    "j_load_kgm2": {
      "type": "number",
      "description": "Load inertia at load shaft [kg\u00b7m\u00b2]."
    },
    "gear_ratio": {
      "type": "number",
      "description": "Current gear ratio N = \u03c9_motor / \u03c9_load (default 1)."
    },
    "mismatch_threshold": {
      "type": "number",
      "description": "Advisory mismatch ratio limit (default 10)."
    }
  },
  "required": [
    "j_motor_kgm2",
    "j_load_kgm2"
  ]
}
```

---

## `motordrive_rms_torque`

Compute RMS torque over a trapezoidal velocity move profile for continuous-rating motor selection.

T_rms = sqrt( (T_a²·dt_a + T_c²·dt_c + T_d²·dt_d + T_dw²·dt_dw) / t_cycle )

Motor continuous torque rating must exceed T_rms.

Input: { t_accel_nm, t_cruise_nm, t_decel_nm, t_dwell_nm, dt_accel_s, dt_cruise_s, dt_decel_s, dt_dwell_s }
Returns: { ok, t_rms_nm, t_peak_nm, cycle_time_s, duty_cycle_active, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "t_accel_nm": {
      "type": "number",
      "description": "Torque during acceleration [N\u00b7m]."
    },
    "t_cruise_nm": {
      "type": "number",
      "description": "Torque during cruise [N\u00b7m]."
    },
    "t_decel_nm": {
      "type": "number",
      "description": "Torque during deceleration [N\u00b7m]."
    },
    "t_dwell_nm": {
      "type": "number",
      "description": "Torque during dwell (holding or 0) [N\u00b7m]."
    },
    "dt_accel_s": {
      "type": "number",
      "description": "Acceleration phase duration [s]."
    },
    "dt_cruise_s": {
      "type": "number",
      "description": "Cruise phase duration [s]."
    },
    "dt_decel_s": {
      "type": "number",
      "description": "Deceleration phase duration [s]."
    },
    "dt_dwell_s": {
      "type": "number",
      "description": "Dwell phase duration [s]."
    }
  },
  "required": [
    "t_accel_nm",
    "t_cruise_nm",
    "t_decel_nm",
    "t_dwell_nm",
    "dt_accel_s",
    "dt_cruise_s",
    "dt_decel_s",
    "dt_dwell_s"
  ]
}
```

---

## `motordrive_motor_constants`

Derive motor constants from datasheet parameters.

Kt [N·m/A] = rated_torque / rated_current
Ke [V·s/rad] = Kt  (equal in SI units)
E_bemf = Ke × ω_no_load
T_stall = Kt × V_rated / R_winding
P_copper = I_rated² × R_winding

Input: { rated_torque_nm, rated_current_a, no_load_speed_rpm, rated_voltage_v, winding_resistance_ohm, poles? }
Returns: { ok, kt_nm_per_a, ke_v_s_per_rad, omega_no_load_rad_s, e_bemf_rated_v, p_copper_w, t_stall_nm, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "rated_torque_nm": {
      "type": "number",
      "description": "Rated output torque [N\u00b7m]."
    },
    "rated_current_a": {
      "type": "number",
      "description": "Rated current [A]."
    },
    "no_load_speed_rpm": {
      "type": "number",
      "description": "No-load speed at rated voltage [RPM]."
    },
    "rated_voltage_v": {
      "type": "number",
      "description": "Rated terminal voltage [V]."
    },
    "winding_resistance_ohm": {
      "type": "number",
      "description": "Phase/armature resistance [\u03a9]."
    },
    "poles": {
      "type": "integer",
      "description": "Number of motor poles (even; default 2)."
    }
  },
  "required": [
    "rated_torque_nm",
    "rated_current_a",
    "no_load_speed_rpm",
    "rated_voltage_v",
    "winding_resistance_ohm"
  ]
}
```

---

## `motordrive_dc_operating_point`

DC brush motor operating point at a given speed and torque.

I_a = T / Kt
E_bemf = Ke × ω
V_terminal = E_bemf + I_a × Ra
η = P_out / (V_t × I_a)

A warning is issued when V_terminal > supply_voltage_v.

Input: { speed_rpm, torque_nm, kt_nm_per_a, ke_v_s_per_rad, winding_resistance_ohm, supply_voltage_v }
Returns: { ok, omega_rad_s, i_a_a, e_bemf_v, v_terminal_v, p_copper_w, p_out_w, p_input_w, efficiency, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "speed_rpm": {
      "type": "number",
      "description": "Shaft speed [RPM]."
    },
    "torque_nm": {
      "type": "number",
      "description": "Output torque [N\u00b7m]."
    },
    "kt_nm_per_a": {
      "type": "number",
      "description": "Torque constant Kt [N\u00b7m/A]."
    },
    "ke_v_s_per_rad": {
      "type": "number",
      "description": "Back-EMF constant Ke [V\u00b7s/rad]."
    },
    "winding_resistance_ohm": {
      "type": "number",
      "description": "Armature resistance [\u03a9]."
    },
    "supply_voltage_v": {
      "type": "number",
      "description": "Available DC supply voltage [V]."
    }
  },
  "required": [
    "speed_rpm",
    "torque_nm",
    "kt_nm_per_a",
    "ke_v_s_per_rad",
    "winding_resistance_ohm",
    "supply_voltage_v"
  ]
}
```

---

## `motordrive_bldc_pmsm_op_point`

BLDC/PMSM operating point using simplified d-q axis model.

Iq = T / (1.5 × p × Kt)  [FOC, p = pole_pairs]
E_ph = Ke × ω_elec / sqrt(3)
V_dc_min ≈ sqrt(2) × V_phase
P_copper = 1.5 × Rs × (Iq² + Id²)

A warning is issued when V_dc_min > dc_link_voltage_v.

Input: { speed_rpm, torque_nm, kt_nm_per_a, ke_v_s_per_rad, phase_resistance_ohm, dc_link_voltage_v, pole_pairs?, id_a? }
Returns: { ok, omega_mech_rad_s, omega_elec_rad_s, iq_a, is_a, e_bemf_v, v_phase_v, v_dc_min_v, p_copper_w, p_out_w, p_input_w, efficiency, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "speed_rpm": {
      "type": "number",
      "description": "Mechanical shaft speed [RPM]."
    },
    "torque_nm": {
      "type": "number",
      "description": "Output torque [N\u00b7m]."
    },
    "kt_nm_per_a": {
      "type": "number",
      "description": "Torque constant Kt [N\u00b7m/A_peak]."
    },
    "ke_v_s_per_rad": {
      "type": "number",
      "description": "Back-EMF constant Ke [V\u00b7s/rad_mech]."
    },
    "phase_resistance_ohm": {
      "type": "number",
      "description": "Per-phase resistance [\u03a9]."
    },
    "dc_link_voltage_v": {
      "type": "number",
      "description": "Available DC bus voltage [V]."
    },
    "pole_pairs": {
      "type": "integer",
      "description": "Number of pole pairs (default 2)."
    },
    "id_a": {
      "type": "number",
      "description": "d-axis current [A] for flux weakening (default 0)."
    }
  },
  "required": [
    "speed_rpm",
    "torque_nm",
    "kt_nm_per_a",
    "ke_v_s_per_rad",
    "phase_resistance_ohm",
    "dc_link_voltage_v"
  ]
}
```

---

## `motordrive_induction_slip_torque`

Basic induction motor torque at a given slip using the approximate equivalent circuit (Chapman §6.4 model).

P_ag = 3 × Vs² × (R2/s) / [(Rs + R2/s)² + X_eq²]
T = P_ag / ω_sync

Warnings for slip > 20 % (unstable region) or slip < 0 (generator mode).

Input: { synchronous_speed_rpm, rotor_resistance_ohm, stator_resistance_ohm, leakage_reactance_ohm, supply_voltage_v, slip }
Returns: { ok, omega_sync_rad_s, omega_rotor_rad_s, rotor_speed_rpm, torque_nm, air_gap_power_w, stator_copper_loss_w, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "synchronous_speed_rpm": {
      "type": "number",
      "description": "Synchronous speed [RPM]."
    },
    "rotor_resistance_ohm": {
      "type": "number",
      "description": "Rotor resistance referred to stator [\u03a9]."
    },
    "stator_resistance_ohm": {
      "type": "number",
      "description": "Stator resistance [\u03a9]."
    },
    "leakage_reactance_ohm": {
      "type": "number",
      "description": "Total leakage reactance [\u03a9]."
    },
    "supply_voltage_v": {
      "type": "number",
      "description": "Per-phase RMS supply voltage [V]."
    },
    "slip": {
      "type": "number",
      "description": "Per-unit slip s = (\u03c9_s \u2212 \u03c9_r) / \u03c9_s (non-zero)."
    }
  },
  "required": [
    "synchronous_speed_rpm",
    "rotor_resistance_ohm",
    "stator_resistance_ohm",
    "leakage_reactance_ohm",
    "supply_voltage_v",
    "slip"
  ]
}
```

---

## `motordrive_inverter_sizing`

Size a three-phase inverter: device ratings, switching loss, conduction loss.

I_device_rated = I_peak / current_derating
V_device_rated = V_dc × 2
P_sw = N_devices × E_sw × fsw
P_cond = phases × 2 × V_drop × I_rms

Input: { peak_phase_current_a, peak_phase_voltage_v, dc_link_voltage_v, switching_freq_hz, conduction_voltage_drop_v?, switching_energy_uj?, phases?, current_derating? }
Returns: { ok, i_device_rated_a, v_device_rated_v, i_rms_a, p_switching_w, p_conduction_w, p_total_loss_w, n_devices, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "peak_phase_current_a": {
      "type": "number",
      "description": "Peak phase current [A]."
    },
    "peak_phase_voltage_v": {
      "type": "number",
      "description": "Peak phase voltage [V]."
    },
    "dc_link_voltage_v": {
      "type": "number",
      "description": "DC bus voltage [V]."
    },
    "switching_freq_hz": {
      "type": "number",
      "description": "PWM switching frequency [Hz]."
    },
    "conduction_voltage_drop_v": {
      "type": "number",
      "description": "Device on-state voltage drop [V] (default 2.0 V)."
    },
    "switching_energy_uj": {
      "type": "number",
      "description": "Per-device switching energy [\u03bcJ/cycle] (default 100 \u03bcJ)."
    },
    "phases": {
      "type": "integer",
      "description": "Number of phases (default 3)."
    },
    "current_derating": {
      "type": "number",
      "description": "Device current derating factor (default 0.80)."
    }
  },
  "required": [
    "peak_phase_current_a",
    "peak_phase_voltage_v",
    "dc_link_voltage_v",
    "switching_freq_hz"
  ]
}
```

---

## `motordrive_regen_energy`

Compute recoverable kinetic energy during regenerative deceleration.

ΔKE = 0.5 × J × (ω_i² − ω_f²)
E_regen = ΔKE × η_drivetrain

Input: { inertia_kgm2, speed_initial_rpm, speed_final_rpm, drivetrain_efficiency? }
Returns: { ok, delta_ke_j, e_regen_j, e_dissipated_j, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "inertia_kgm2": {
      "type": "number",
      "description": "Total rotating inertia [kg\u00b7m\u00b2]."
    },
    "speed_initial_rpm": {
      "type": "number",
      "description": "Initial speed [RPM]."
    },
    "speed_final_rpm": {
      "type": "number",
      "description": "Final speed [RPM] (must be < initial)."
    },
    "drivetrain_efficiency": {
      "type": "number",
      "description": "Round-trip drivetrain efficiency (default 0.90)."
    }
  },
  "required": [
    "inertia_kgm2",
    "speed_initial_rpm",
    "speed_final_rpm"
  ]
}
```

---

## `motordrive_brake_resistor`

Size a brake (dynamic braking) resistor for a DC-link inverter.

V_brake = V_dc × (1 + overvoltage_margin)
R_brake = V_brake² × t_discharge / (2 × E_regen)
P_avg = E_regen / t_discharge
P_peak = V_brake² / R_brake

Input: { regen_energy_j, dc_link_voltage_v, discharge_time_s, overvoltage_margin_frac? }
Returns: { ok, v_brake_v, r_brake_ohm, p_avg_w, p_peak_w, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "regen_energy_j": {
      "type": "number",
      "description": "Total energy to dissipate [J]."
    },
    "dc_link_voltage_v": {
      "type": "number",
      "description": "Nominal DC-link voltage [V]."
    },
    "discharge_time_s": {
      "type": "number",
      "description": "Maximum discharge time [s]."
    },
    "overvoltage_margin_frac": {
      "type": "number",
      "description": "Fractional overvoltage above nominal (default 0.10 = 10 %)."
    }
  },
  "required": [
    "regen_energy_j",
    "dc_link_voltage_v",
    "discharge_time_s"
  ]
}
```

---

## `motordrive_thermal_duty`

Motor thermal duty-cycle check: steady-state winding temperature from ambient, losses, and thermal resistance.

P_eff = P_loss × duty_cycle
ΔT = P_eff × Rth_winding_ambient
T_winding = T_ambient + ΔT

With thermal time constant: ΔT = ΔT_ss × (1 − exp(−t_on / τ))

A warning is issued when T_winding > t_max_c (default 130 °C Class F).

Input: { p_loss_w, rth_winding_ambient, t_ambient_c, duty_cycle?, t_max_c?, thermal_time_constant_s?, cycle_time_s? }
Returns: { ok, t_winding_c, delta_t_k, t_margin_k, over_temp, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p_loss_w": {
      "type": "number",
      "description": "Total motor loss at operating point [W]."
    },
    "rth_winding_ambient": {
      "type": "number",
      "description": "Winding-to-ambient thermal resistance [\u00b0C/W]."
    },
    "t_ambient_c": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C]."
    },
    "duty_cycle": {
      "type": "number",
      "description": "Duty cycle S (0 < S \u2264 1, default 1.0 = continuous)."
    },
    "t_max_c": {
      "type": "number",
      "description": "Maximum winding temperature [\u00b0C] (default 130 \u00b0C Class F)."
    },
    "thermal_time_constant_s": {
      "type": "number",
      "description": "Motor thermal time constant [s] (0 = not used)."
    },
    "cycle_time_s": {
      "type": "number",
      "description": "Duty cycle period [s] (0 = not used)."
    }
  },
  "required": [
    "p_loss_w",
    "rth_winding_ambient",
    "t_ambient_c"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
