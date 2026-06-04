# powerconv

*Module: `kerf_electronics.powerconv.tools` · Domain: electronics*

This module registers **6** LLM tool(s):

- [`powerconv_buck_design`](#powerconv-buck-design)
- [`powerconv_boost_design`](#powerconv-boost-design)
- [`powerconv_buck_boost_design`](#powerconv-buck-boost-design)
- [`powerconv_flyback_design`](#powerconv-flyback-design)
- [`powerconv_sepic_design`](#powerconv-sepic-design)
- [`powerconv_thermal`](#powerconv-thermal)

---

## `powerconv_buck_design`

Steady-state CCM design for a synchronous/non-synchronous buck (step-down) converter.

D = Vout / Vin
L = (Vin − Vout) × D / (fsw × ΔIL)
I_L_peak = Iout + ΔIL/2
V_sw_stress = Vin

Warnings: DCM-when-CCM-assumed, near-CCM-boundary, high duty, efficiency-low.

Input: { v_in, v_out, i_out, fsw, ripple_frac?, c_out_f?, esr_ohm?, r_ds_on?, v_diode?, dcr_ohm?, t_rise_s?, t_fall_s? }
Returns: { ok, duty, l_h, l_crit_h, ccm, delta_il_a, i_l_peak_a, i_l_valley_a, i_l_rms_a, i_sw_rms_a, i_diode_rms_a, v_sw_stress_v, v_diode_stress_v, c_out_min_f, delta_v_esr_v, delta_v_cap_v, delta_v_total_v, p_sw_cond_w, p_sw_switch_w, p_diode_w, p_dcr_w, p_total_loss_w, p_out_w, efficiency, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_in": {
      "type": "number",
      "description": "Input voltage [V]."
    },
    "v_out": {
      "type": "number",
      "description": "Output voltage [V] (must be < v_in)."
    },
    "i_out": {
      "type": "number",
      "description": "Output (load) current [A]."
    },
    "fsw": {
      "type": "number",
      "description": "Switching frequency [Hz]."
    },
    "ripple_frac": {
      "type": "number",
      "description": "Inductor current ripple as fraction of Iout (default 0.30)."
    },
    "c_out_f": {
      "type": "number",
      "description": "Output capacitor [F] (default 100 \u00b5F)."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Output cap ESR [\u03a9] (default 20 m\u03a9)."
    },
    "r_ds_on": {
      "type": "number",
      "description": "Switch Rds(on) [\u03a9] (default 50 m\u03a9)."
    },
    "v_diode": {
      "type": "number",
      "description": "Catch diode forward voltage [V] (default 0.5 V)."
    },
    "dcr_ohm": {
      "type": "number",
      "description": "Inductor DCR [\u03a9] (default 10 m\u03a9)."
    },
    "t_rise_s": {
      "type": "number",
      "description": "Switch current rise time [s] (default 20 ns)."
    },
    "t_fall_s": {
      "type": "number",
      "description": "Switch current fall time [s] (default 20 ns)."
    }
  },
  "required": [
    "v_in",
    "v_out",
    "i_out",
    "fsw"
  ]
}
```

---

## `powerconv_boost_design`

Steady-state CCM design for a boost (step-up) converter.

D = 1 − Vin / Vout
L = Vin × D / (fsw × ΔIL)
V_sw_stress = Vout
f_RHP = (1−D)² × Vout / (2π × L × Iout)

Warnings: DCM-when-CCM-assumed, RHP-zero < 20 % fsw (bandwidth limitation), high duty, efficiency-low.

Input: { v_in, v_out, i_out, fsw, ripple_frac?, c_out_f?, esr_ohm?, r_ds_on?, v_diode?, dcr_ohm?, t_rise_s?, t_fall_s? }
Returns: { ok, duty, l_h, l_crit_h, ccm, f_rhp_hz, delta_il_a, i_in_avg_a, i_l_peak_a, i_l_rms_a, i_sw_rms_a, i_diode_rms_a, v_sw_stress_v, v_diode_stress_v, c_out_min_f, delta_v_esr_v, delta_v_cap_v, delta_v_total_v, p_sw_cond_w, p_sw_switch_w, p_diode_w, p_dcr_w, p_total_loss_w, p_out_w, efficiency, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_in": {
      "type": "number",
      "description": "Input voltage [V]."
    },
    "v_out": {
      "type": "number",
      "description": "Output voltage [V] (must be > v_in)."
    },
    "i_out": {
      "type": "number",
      "description": "Output (load) current [A]."
    },
    "fsw": {
      "type": "number",
      "description": "Switching frequency [Hz]."
    },
    "ripple_frac": {
      "type": "number",
      "description": "Inductor current ripple fraction of Iin_avg (default 0.30)."
    },
    "c_out_f": {
      "type": "number",
      "description": "Output capacitor [F] (default 100 \u00b5F)."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Output cap ESR [\u03a9] (default 20 m\u03a9)."
    },
    "r_ds_on": {
      "type": "number",
      "description": "Switch Rds(on) [\u03a9] (default 50 m\u03a9)."
    },
    "v_diode": {
      "type": "number",
      "description": "Boost diode forward voltage [V] (default 0.5 V)."
    },
    "dcr_ohm": {
      "type": "number",
      "description": "Inductor DCR [\u03a9] (default 10 m\u03a9)."
    },
    "t_rise_s": {
      "type": "number",
      "description": "Switch current rise time [s] (default 20 ns)."
    },
    "t_fall_s": {
      "type": "number",
      "description": "Switch current fall time [s] (default 20 ns)."
    }
  },
  "required": [
    "v_in",
    "v_out",
    "i_out",
    "fsw"
  ]
}
```

---

## `powerconv_buck_boost_design`

Steady-state CCM design for an inverting buck-boost converter.

D = Vout_mag / (Vin + Vout_mag)  [output is −Vout_mag]
L = Vin × D / (fsw × ΔIL)
V_sw_stress = Vin + Vout_mag
f_RHP = (1−D)² × Vout_mag / (2π × L × Iout)

Warnings: polarity-inversion note, DCM-when-CCM-assumed, RHP-limited-bandwidth, efficiency-low.

Input: { v_in, v_out_mag, i_out, fsw, ripple_frac?, c_out_f?, esr_ohm?, r_ds_on?, v_diode?, dcr_ohm?, t_rise_s?, t_fall_s? }
Returns: { ok, duty, polarity_note, l_h, l_crit_h, ccm, f_rhp_hz, delta_il_a, i_l_peak_a, i_l_rms_a, i_sw_rms_a, i_diode_rms_a, v_sw_stress_v, v_diode_stress_v, c_out_min_f, delta_v_esr_v, delta_v_cap_v, delta_v_total_v, p_sw_cond_w, p_sw_switch_w, p_diode_w, p_dcr_w, p_total_loss_w, p_out_w, efficiency, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_in": {
      "type": "number",
      "description": "Input voltage [V]."
    },
    "v_out_mag": {
      "type": "number",
      "description": "Output voltage magnitude [V] (output is \u2212v_out_mag)."
    },
    "i_out": {
      "type": "number",
      "description": "Output (load) current magnitude [A]."
    },
    "fsw": {
      "type": "number",
      "description": "Switching frequency [Hz]."
    },
    "ripple_frac": {
      "type": "number",
      "description": "Inductor current ripple fraction (default 0.30)."
    },
    "c_out_f": {
      "type": "number",
      "description": "Output capacitor [F] (default 100 \u00b5F)."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Output cap ESR [\u03a9] (default 20 m\u03a9)."
    },
    "r_ds_on": {
      "type": "number",
      "description": "Switch Rds(on) [\u03a9] (default 50 m\u03a9)."
    },
    "v_diode": {
      "type": "number",
      "description": "Catch diode forward voltage [V] (default 0.5 V)."
    },
    "dcr_ohm": {
      "type": "number",
      "description": "Inductor DCR [\u03a9] (default 10 m\u03a9)."
    },
    "t_rise_s": {
      "type": "number",
      "description": "Switch current rise time [s] (default 20 ns)."
    },
    "t_fall_s": {
      "type": "number",
      "description": "Switch current fall time [s] (default 20 ns)."
    }
  },
  "required": [
    "v_in",
    "v_out_mag",
    "i_out",
    "fsw"
  ]
}
```

---

## `powerconv_flyback_design`

Isolated flyback converter steady-state CCM design.

n = Np/Ns turns ratio = Vin × D / (Vout × (1−D))  [D ≈ 0.40 if n not given]
Lp = Vin × D / (fsw × ΔIp)
Ip_peak = n × Iout / (1−D) + ΔIp/2
V_sw_stress = Vin + n × Vout  (no RCD clamp)

Warnings: DCM-when-CCM-assumed, RCD-snubber-required (always), efficiency-low.

Input: { v_in, v_out, i_out, fsw, n_turns_ratio?, ripple_frac?, c_out_f?, esr_ohm?, r_ds_on?, v_diode?, dcr_primary_ohm?, t_rise_s?, t_fall_s?, snubber_note? }
Returns: { ok, duty, n_turns_ratio, l_primary_h, l_primary_crit_h, ccm, ip_peak_a, ip_rms_a, is_peak_a, v_sw_stress_v, v_sec_diode_stress_v, c_out_min_f, delta_v_esr_v, delta_v_cap_v, delta_v_total_v, p_sw_cond_w, p_sw_switch_w, p_diode_w, p_dcr_w, p_total_loss_w, p_out_w, efficiency, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_in": {
      "type": "number",
      "description": "Input voltage [V]."
    },
    "v_out": {
      "type": "number",
      "description": "Output voltage [V]."
    },
    "i_out": {
      "type": "number",
      "description": "Output (load) current [A]."
    },
    "fsw": {
      "type": "number",
      "description": "Switching frequency [Hz]."
    },
    "n_turns_ratio": {
      "type": "number",
      "description": "Primary-to-secondary turns ratio Np/Ns (optional; default: computed for D \u2248 0.40)."
    },
    "ripple_frac": {
      "type": "number",
      "description": "Primary current ripple fraction (default 0.40)."
    },
    "c_out_f": {
      "type": "number",
      "description": "Output capacitor [F] (default 100 \u00b5F)."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Output cap ESR [\u03a9] (default 50 m\u03a9)."
    },
    "r_ds_on": {
      "type": "number",
      "description": "Primary switch Rds(on) [\u03a9] (default 200 m\u03a9)."
    },
    "v_diode": {
      "type": "number",
      "description": "Secondary diode Vf [V] (default 0.7 V)."
    },
    "dcr_primary_ohm": {
      "type": "number",
      "description": "Primary winding DCR [\u03a9] (default 100 m\u03a9)."
    },
    "t_rise_s": {
      "type": "number",
      "description": "Switch current rise time [s] (default 50 ns)."
    },
    "t_fall_s": {
      "type": "number",
      "description": "Switch current fall time [s] (default 50 ns)."
    },
    "snubber_note": {
      "type": "boolean",
      "description": "Include RCD snubber note in warnings (default true)."
    }
  },
  "required": [
    "v_in",
    "v_out",
    "i_out",
    "fsw"
  ]
}
```

---

## `powerconv_sepic_design`

Steady-state CCM design for a SEPIC converter (non-inverting, buck or boost).

D = Vout / (Vin + Vout)
L1 = L2 = Vin × D / (fsw × ΔIL1)
I_sw_peak = IL1_peak + IL2_peak
V_sw_stress = Vin + Vout
V_C1 = Vin  [coupling cap steady-state]

Warnings: DCM-when-CCM-assumed, coupling-cap ESR note, efficiency-low.

Input: { v_in, v_out, i_out, fsw, ripple_frac?, c_out_f?, c_coupling_f?, esr_ohm?, r_ds_on?, v_diode?, dcr_ohm?, t_rise_s?, t_fall_s? }
Returns: { ok, duty, l1_h, l2_h, l_crit_h, ccm, delta_il1_a, i_in_avg_a, i_sw_peak_a, i_sw_rms_a, i_diode_rms_a, i_l1_rms_a, i_l2_rms_a, v_c1_v, v_sw_stress_v, v_diode_stress_v, c_out_min_f, c_coupling_min_f, delta_v_esr_v, delta_v_cap_v, delta_v_total_v, p_sw_cond_w, p_sw_switch_w, p_diode_w, p_dcr_w, p_total_loss_w, p_out_w, efficiency, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_in": {
      "type": "number",
      "description": "Input voltage [V]."
    },
    "v_out": {
      "type": "number",
      "description": "Output voltage [V]."
    },
    "i_out": {
      "type": "number",
      "description": "Output (load) current [A]."
    },
    "fsw": {
      "type": "number",
      "description": "Switching frequency [Hz]."
    },
    "ripple_frac": {
      "type": "number",
      "description": "L1 current ripple fraction of Iin_avg (default 0.30)."
    },
    "c_out_f": {
      "type": "number",
      "description": "Output capacitor [F] (default 100 \u00b5F)."
    },
    "c_coupling_f": {
      "type": "number",
      "description": "Series coupling capacitor C1 [F] (default 10 \u00b5F)."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Output cap ESR [\u03a9] (default 30 m\u03a9)."
    },
    "r_ds_on": {
      "type": "number",
      "description": "Switch Rds(on) [\u03a9] (default 100 m\u03a9)."
    },
    "v_diode": {
      "type": "number",
      "description": "Output diode Vf [V] (default 0.5 V)."
    },
    "dcr_ohm": {
      "type": "number",
      "description": "Inductor DCR per inductor [\u03a9] (default 20 m\u03a9)."
    },
    "t_rise_s": {
      "type": "number",
      "description": "Switch current rise time [s] (default 30 ns)."
    },
    "t_fall_s": {
      "type": "number",
      "description": "Switch current fall time [s] (default 30 ns)."
    }
  },
  "required": [
    "v_in",
    "v_out",
    "i_out",
    "fsw"
  ]
}
```

---

## `powerconv_thermal`

Junction temperature estimate for a switching converter semiconductor.

Single-package: Tj = T_ambient + P_loss × Rth_JA
With heatsink: Tj = T_ambient + P_loss × (Rth_JC + Rth_CS + Rth_SA)

A warning is issued when Tj > t_j_max_c (default 150 °C).

Input: { p_loss_w, rth_ja, t_ambient_c?, t_j_max_c?, rth_jc?, rth_cs? }
Returns: { ok, t_junction_c, delta_t_k, t_margin_k, over_temp, rth_total, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p_loss_w": {
      "type": "number",
      "description": "Total semiconductor power dissipation [W]."
    },
    "rth_ja": {
      "type": "number",
      "description": "Junction-to-ambient thermal resistance [\u00b0C/W] (or Rth_SA when rth_jc+rth_cs provided)."
    },
    "t_ambient_c": {
      "type": "number",
      "description": "Ambient temperature [\u00b0C] (default 25 \u00b0C)."
    },
    "t_j_max_c": {
      "type": "number",
      "description": "Maximum junction temperature [\u00b0C] (default 150 \u00b0C)."
    },
    "rth_jc": {
      "type": "number",
      "description": "Junction-to-case thermal resistance [\u00b0C/W] (optional, for discrete with heatsink)."
    },
    "rth_cs": {
      "type": "number",
      "description": "Case-to-heatsink thermal resistance [\u00b0C/W] (optional)."
    }
  },
  "required": [
    "p_loss_w",
    "rth_ja"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
