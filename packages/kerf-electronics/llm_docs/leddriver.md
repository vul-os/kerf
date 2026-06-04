# leddriver

*Module: `kerf_electronics.leddriver.tools` · Domain: electronics*

This module registers **7** LLM tool(s):

- [`led_string_layout`](#led-string-layout)
- [`led_series_resistor`](#led-series-resistor)
- [`led_driver_topology`](#led-driver-topology)
- [`led_buck_cc_design`](#led-buck-cc-design)
- [`led_boost_cc_design`](#led-boost-cc-design)
- [`led_thermal_derating`](#led-thermal-derating)
- [`led_pwm_dimming`](#led-pwm-dimming)

---

## `led_string_layout`

Determine the series/parallel LED string configuration from supply voltage, target luminous flux, and per-LED electrical/optical parameters.

Algorithm:
  1. n_series = floor((V_supply − vf_headroom) / Vf)
  2. lm per string derated by binning_headroom_frac
  3. n_parallel = ceil(target_lumens / lm_per_string)

Warnings are issued for string mismatch (parallel strings without per-string CC), low efficiency (V_string / V_supply < 60 %), and exceeding max_parallel_strings.

Input: { supply_v, target_lumens, led_vf, led_if_a, led_lumens, vf_headroom_v?, binning_headroom_frac?, max_parallel_strings? }
Returns: { ok, n_series, n_parallel, n_total, v_string_v, i_total_a, total_lumens_achievable, input_power_w, efficiency_lm_per_w, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "supply_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "target_lumens": {
      "type": "number",
      "description": "Required total luminous flux [lm]."
    },
    "led_vf": {
      "type": "number",
      "description": "Typical LED forward voltage [V]."
    },
    "led_if_a": {
      "type": "number",
      "description": "Rated LED forward current [A]."
    },
    "led_lumens": {
      "type": "number",
      "description": "Luminous flux per LED at led_if_a [lm]."
    },
    "vf_headroom_v": {
      "type": "number",
      "description": "Minimum driver headroom above V_string [V] (default 1.5 V)."
    },
    "binning_headroom_frac": {
      "type": "number",
      "description": "Fractional lumen derating for Vf/If bin spread (default 0.05)."
    },
    "max_parallel_strings": {
      "type": "integer",
      "description": "Advisory maximum number of parallel strings (default 8)."
    }
  },
  "required": [
    "supply_v",
    "target_lumens",
    "led_vf",
    "led_if_a",
    "led_lumens"
  ]
}
```

---

## `led_series_resistor`

Size a series resistor for an LED string and compute resistor power dissipation and overall efficiency.

R = (V_supply − n_series × Vf) / If
P_R = R × If²
efficiency = n_series × Vf / V_supply

A warning is issued when efficiency < 60 %.

Input: { supply_v, led_vf, led_if_a, n_series? }
Returns: { ok, r_series_ohm, p_resistor_w, p_led_w, efficiency, v_string_v, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "supply_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "led_vf": {
      "type": "number",
      "description": "LED forward voltage [V]."
    },
    "led_if_a": {
      "type": "number",
      "description": "Target LED forward current [A]."
    },
    "n_series": {
      "type": "integer",
      "description": "Number of LEDs in series (default 1)."
    }
  },
  "required": [
    "supply_v",
    "led_vf",
    "led_if_a"
  ]
}
```

---

## `led_driver_topology`

Recommend linear constant-current (LDO-type) or switching (buck/boost) driver topology based on supply/string voltage ratio and efficiency target.

Decision rules:
  V_string > V_supply → boost required
  linear_eff ≥ efficiency_threshold → linear acceptable
  otherwise → buck switching recommended

Input: { supply_v, v_string_v, led_if_a, efficiency_threshold? }
Returns: { ok, topology, linear_efficiency, p_linear_dissipation_w, v_drop_v, recommend_switching, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "supply_v": {
      "type": "number",
      "description": "Supply voltage [V]."
    },
    "v_string_v": {
      "type": "number",
      "description": "LED string voltage [V]."
    },
    "led_if_a": {
      "type": "number",
      "description": "LED forward current [A]."
    },
    "efficiency_threshold": {
      "type": "number",
      "description": "Minimum acceptable linear efficiency (default 0.80)."
    }
  },
  "required": [
    "supply_v",
    "v_string_v",
    "led_if_a"
  ]
}
```

---

## `led_buck_cc_design`

Design a buck converter constant-current LED driver.

Computes duty cycle D = V_string / (V_in × η), inductor value from peak-to-peak ripple spec, output capacitor for voltage ripple budget, and switch peak voltage/current stress.

Requires V_string < V_in (step-down).  Use led_boost_cc_design for step-up.

Input: { v_in, v_string, i_led, fsw_hz, inductor_ripple_frac?, cap_ripple_v?, eta? }
Returns: { ok, duty_cycle, l_inductor_h, c_out_f, i_l_peak_a, i_l_valley_a, delta_il_a, v_sw_max_v, i_sw_peak_a, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_in": {
      "type": "number",
      "description": "Input voltage [V]."
    },
    "v_string": {
      "type": "number",
      "description": "LED string voltage (converter output) [V]."
    },
    "i_led": {
      "type": "number",
      "description": "LED forward current (converter output current) [A]."
    },
    "fsw_hz": {
      "type": "number",
      "description": "Switching frequency [Hz]."
    },
    "inductor_ripple_frac": {
      "type": "number",
      "description": "Peak-to-peak inductor current ripple / I_led (default 0.20)."
    },
    "cap_ripple_v": {
      "type": "number",
      "description": "Maximum output voltage ripple [V] (default 0.05 V)."
    },
    "eta": {
      "type": "number",
      "description": "Estimated converter efficiency 0 < \u03b7 \u2264 1 (default 0.90)."
    }
  },
  "required": [
    "v_in",
    "v_string",
    "i_led",
    "fsw_hz"
  ]
}
```

---

## `led_boost_cc_design`

Design a boost converter constant-current LED driver.

Computes duty cycle D = 1 − V_in × η / V_string, inductor from ripple spec, output capacitor, and switch stress.

Requires V_string > V_in (step-up).  Use led_buck_cc_design for step-down.

Input: { v_in, v_string, i_led, fsw_hz, inductor_ripple_frac?, cap_ripple_v?, eta? }
Returns: { ok, duty_cycle, l_inductor_h, c_out_f, i_in_a, i_l_peak_a, delta_il_a, v_sw_max_v, i_sw_peak_a, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_in": {
      "type": "number",
      "description": "Input voltage [V]."
    },
    "v_string": {
      "type": "number",
      "description": "LED string voltage (converter output) [V]."
    },
    "i_led": {
      "type": "number",
      "description": "LED forward current [A]."
    },
    "fsw_hz": {
      "type": "number",
      "description": "Switching frequency [Hz]."
    },
    "inductor_ripple_frac": {
      "type": "number",
      "description": "Peak-to-peak inductor current ripple / I_in (default 0.20)."
    },
    "cap_ripple_v": {
      "type": "number",
      "description": "Maximum output voltage ripple [V] (default 0.10 V)."
    },
    "eta": {
      "type": "number",
      "description": "Estimated converter efficiency 0 < \u03b7 \u2264 1 (default 0.88)."
    }
  },
  "required": [
    "v_in",
    "v_string",
    "i_led",
    "fsw_hz"
  ]
}
```

---

## `led_thermal_derating`

Compute LED junction temperature and apply lumen/Vf thermal derating.

Thermal model: T_j = T_ambient + P × (Rth_jc + Rth_cs)
Derating (linear from datasheet): ΔT = T_j − 25 °C
  lm_derated = lm_rated × (1 − lm_derating_per_k × ΔT)
  vf_derated = vf_rated × (1 − vf_derating_per_k × ΔT)

Warnings issued for over-temperature (T_j > tj_max_c) and severe lumen derating (> 50 %).

Input: { p_dissipated_w, rth_jc, rth_cs, t_ambient_c, lm_rated, vf_rated_v, lm_derating_per_k?, vf_derating_per_k?, tj_max_c? }
Returns: { ok, t_junction_c, delta_t_k, lm_derated, vf_derated_v, lm_derating_frac, vf_derating_frac, over_temp, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p_dissipated_w": {
      "type": "number",
      "description": "Total power dissipated in LED junction [W]."
    },
    "rth_jc": {
      "type": "number",
      "description": "Junction-to-case thermal resistance [\u00b0C/W]."
    },
    "rth_cs": {
      "type": "number",
      "description": "Case-to-sink (or board) thermal resistance [\u00b0C/W]."
    },
    "t_ambient_c": {
      "type": "number",
      "description": "Ambient (heatsink) temperature [\u00b0C]."
    },
    "lm_rated": {
      "type": "number",
      "description": "Rated luminous flux at 25 \u00b0C [lm]."
    },
    "vf_rated_v": {
      "type": "number",
      "description": "Rated forward voltage at 25 \u00b0C [V]."
    },
    "lm_derating_per_k": {
      "type": "number",
      "description": "Fractional lm decrease per \u00b0C above 25 \u00b0C (default 0.005 = 0.5 %/K)."
    },
    "vf_derating_per_k": {
      "type": "number",
      "description": "Fractional Vf decrease per \u00b0C above 25 \u00b0C (default 0.002 = 0.2 %/K)."
    },
    "tj_max_c": {
      "type": "number",
      "description": "Maximum rated junction temperature [\u00b0C] (default 125 \u00b0C)."
    }
  },
  "required": [
    "p_dissipated_w",
    "rth_jc",
    "rth_cs",
    "t_ambient_c",
    "lm_rated",
    "vf_rated_v"
  ]
}
```

---

## `led_pwm_dimming`

Compute average LED current, apparent brightness ratio, and percent-flicker for PWM LED dimming.

I_avg = duty_cycle × I_peak
brightness_ratio = duty_cycle  (approximately linear for LEDs)
percent_flicker = 100 %  (worst-case ideal PWM: I_max=I_peak, I_min=0)

ENERGY STAR flicker criterion: percent_flicker ≤ 30 % below 1 kHz.
A 'visible_flicker' warning is issued when PWM frequency < 1 kHz.

Input: { pwm_freq_hz, duty_cycle, i_peak_a }
Returns: { ok, i_avg_a, brightness_ratio, percent_flicker, pwm_period_s, visible_flicker_risk, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pwm_freq_hz": {
      "type": "number",
      "description": "PWM switching frequency [Hz]."
    },
    "duty_cycle": {
      "type": "number",
      "description": "PWM duty cycle (0 < D \u2264 1)."
    },
    "i_peak_a": {
      "type": "number",
      "description": "Peak LED current during on-time [A]."
    }
  },
  "required": [
    "pwm_freq_hz",
    "duty_cycle",
    "i_peak_a"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
