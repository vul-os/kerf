# oscillator

*Module: `kerf_electronics.oscillator.tools` · Domain: electronics*

This module registers **12** LLM tool(s):

- [`osc_crystal_load_caps`](#osc-crystal-load-caps)
- [`osc_pierce_neg_resistance`](#osc-pierce-neg-resistance)
- [`osc_drive_level`](#osc-drive-level)
- [`osc_frequency_pulling`](#osc-frequency-pulling)
- [`osc_ppm_budget`](#osc-ppm-budget)
- [`osc_rc_frequency`](#osc-rc-frequency)
- [`osc_lc_frequency`](#osc-lc-frequency)
- [`osc_ring_frequency`](#osc-ring-frequency)
- [`pll_divider_n`](#pll-divider-n)
- [`pll_loop_filter`](#pll-loop-filter)
- [`pll_lock_time`](#pll-lock-time)
- [`pll_phase_noise_to_jitter`](#pll-phase-noise-to-jitter)

---

## `osc_crystal_load_caps`

Calculate crystal load capacitance (CL) and recommend external capacitor values for a Pierce or parallel-resonance oscillator.

Effective CL seen by the crystal:
  CL = (C1_ext × C2_ext) / (C1_ext + C2_ext) + Cstray

Symmetric external caps for target CL:
  C_ext = 2 × (CL_target − Cstray)

Input: { cl_target_f, cstray_f?, c1_ext_f?, c2_ext_f? }
Returns: { ok, cl_target_pf, c_ext_symmetric_pf, cl_actual_pf?, cl_error_ppm? }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "cl_target_f": {
      "type": "number",
      "description": "Target crystal load capacitance [F], e.g. 12e-12 for 12 pF."
    },
    "cstray_f": {
      "type": "number",
      "description": "PCB stray capacitance per node [F] (default 3e-12 = 3 pF)."
    },
    "c1_ext_f": {
      "type": "number",
      "description": "First external load capacitor [F] (optional, for verification)."
    },
    "c2_ext_f": {
      "type": "number",
      "description": "Second external load capacitor [F] (optional, for verification)."
    }
  },
  "required": [
    "cl_target_f"
  ]
}
```

---

## `osc_pierce_neg_resistance`

Compute Pierce oscillator negative resistance and gm margin.

Model (Rohde & Kuhn 2005; Vittoz 1988):
  |−Rn| = gm / (ω² × C1 × C2)

Oscillation starts when |−Rn| ≥ safety_factor × ESR (typically 3–5×).
gm_margin = |−Rn| / ESR — must be ≥ safety_factor.

Input: { freq_hz, gm_s, c1_f, c2_f, esr_ohm, safety_factor? }
Returns: { ok, neg_resistance_ohm, gm_margin, sufficient_gm, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Crystal nominal frequency [Hz]."
    },
    "gm_s": {
      "type": "number",
      "description": "Inverting amplifier transconductance [S] (A/V)."
    },
    "c1_f": {
      "type": "number",
      "description": "Load capacitor on input side [F]."
    },
    "c2_f": {
      "type": "number",
      "description": "Load capacitor on output side [F]."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Crystal equivalent series resistance [\u03a9]."
    },
    "safety_factor": {
      "type": "number",
      "description": "Negative-resistance safety margin (default 3)."
    }
  },
  "required": [
    "freq_hz",
    "gm_s",
    "c1_f",
    "c2_f",
    "esr_ohm"
  ]
}
```

---

## `osc_drive_level`

Estimate power dissipated in the crystal (drive level) in a Pierce oscillator.

Simplified model (Baba & Yoon 2003 / Frerking 1978):
  I_rms ≈ ω × CL × V_rms   (current through load cap)
  P_xtal = I_rms² × ESR

Over-drive damages the crystal. Typical max drive level: 10–100 μW.

Input: { freq_hz, esr_ohm, c_load_f, v_osc_v, max_drive_level_uw? }
Returns: { ok, drive_level_uw, over_drive, i_rms_a, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Oscillation frequency [Hz]."
    },
    "esr_ohm": {
      "type": "number",
      "description": "Crystal equivalent series resistance [\u03a9]."
    },
    "c_load_f": {
      "type": "number",
      "description": "Crystal load capacitance [F]."
    },
    "v_osc_v": {
      "type": "number",
      "description": "Oscillation voltage peak amplitude [V]."
    },
    "max_drive_level_uw": {
      "type": "number",
      "description": "Maximum crystal drive level [\u03bcW] (default 100 \u03bcW)."
    }
  },
  "required": [
    "freq_hz",
    "esr_ohm",
    "c_load_f",
    "v_osc_v"
  ]
}
```

---

## `osc_frequency_pulling`

Compute crystal oscillator frequency pulling due to load capacitance deviation from the nominal CL specification.

First-order approximation (IEC 60444-5):
  Δf/f ≈ (Cm × ΔCL) / (2 × (C0 + CL_nom)²)   [ppm × 1e6]

Exact model also computed:
  Δf/f = (Cm/2) × [1/(C0+CL_act) − 1/(C0+CL_nom)]

Input: { freq_hz, cm_f, c0_f, cl_nominal_f, cl_actual_f }
Returns: { ok, delta_f_ppm, delta_f_ppm_exact, delta_f_hz, delta_f_hz_exact }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "freq_hz": {
      "type": "number",
      "description": "Crystal nominal frequency [Hz]."
    },
    "cm_f": {
      "type": "number",
      "description": "Motional (series) capacitance Cm [F], e.g. 10e-15 (10 fF)."
    },
    "c0_f": {
      "type": "number",
      "description": "Shunt (parallel) capacitance C0 [F], e.g. 3e-12 (3 pF)."
    },
    "cl_nominal_f": {
      "type": "number",
      "description": "Crystal nominal load capacitance [F] (from crystal datasheet)."
    },
    "cl_actual_f": {
      "type": "number",
      "description": "Actual PCB load capacitance [F]."
    }
  },
  "required": [
    "freq_hz",
    "cm_f",
    "c0_f",
    "cl_nominal_f",
    "cl_actual_f"
  ]
}
```

---

## `osc_ppm_budget`

Compute crystal oscillator frequency accuracy error budget using root-sum-of-squares (RSS) combination of independent error sources.

  total_ppm = sqrt(initial² + temp² + aging² + load²)

Each term is the worst-case ±magnitude in ppm (provide absolute values).

Input: { initial_tolerance_ppm, temp_ppm, aging_ppm, load_ppm, budget_limit_ppm? }
Returns: { ok, total_ppm, within_budget?, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "initial_tolerance_ppm": {
      "type": "number",
      "description": "Initial frequency tolerance at calibration [ppm]."
    },
    "temp_ppm": {
      "type": "number",
      "description": "Temperature coefficient contribution [ppm] over operating range."
    },
    "aging_ppm": {
      "type": "number",
      "description": "Aging contribution over product lifetime [ppm/year \u00d7 years]."
    },
    "load_ppm": {
      "type": "number",
      "description": "Load-pulling and supply voltage contribution [ppm]."
    },
    "budget_limit_ppm": {
      "type": "number",
      "description": "System frequency budget limit [ppm] (optional)."
    }
  },
  "required": [
    "initial_tolerance_ppm",
    "temp_ppm",
    "aging_ppm",
    "load_ppm"
  ]
}
```

---

## `osc_rc_frequency`

Compute RC oscillator frequency.

Ideal: f = 1 / (2π × R × C)

For CMOS Schmitt-trigger oscillator: f ≈ 1 / (2.2 × R × C)
  → set rc_factor = 2.2/(2π) ≈ 0.3502

Input: { r_ohm, c_f, rc_factor? }
Returns: { ok, freq_hz, period_s, tau_s }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_ohm": {
      "type": "number",
      "description": "Resistance [\u03a9]."
    },
    "c_f": {
      "type": "number",
      "description": "Capacitance [F]."
    },
    "rc_factor": {
      "type": "number",
      "description": "Multiplier on R\u00d7C (default 1.0 \u2192 ideal 1/(2\u03c0RC)). Use 2.2/(2\u03c0) \u2248 0.3502 for CMOS Schmitt variant."
    }
  },
  "required": [
    "r_ohm",
    "c_f"
  ]
}
```

---

## `osc_lc_frequency`

Compute LC oscillator resonant frequency (Colpitts, Clapp, Hartley, etc.).

  f = 1 / (2π × sqrt(L × C))

For Colpitts: C_eff = C1×C2/(C1+C2).
For Clapp: C_eff includes series tuning cap.

Input: { l_h, c_f }
Returns: { ok, freq_hz, omega_rad_s, period_s }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "l_h": {
      "type": "number",
      "description": "Inductance [H], e.g. 100e-9 for 100 nH."
    },
    "c_f": {
      "type": "number",
      "description": "Effective tank capacitance [F], e.g. 10e-12 for 10 pF."
    }
  },
  "required": [
    "l_h",
    "c_f"
  ]
}
```

---

## `osc_ring_frequency`

Compute ring oscillator fundamental frequency.

  f = 1 / (2 × N × τ_pd)

N = number of inverting stages (must be odd for oscillation: 3, 5, 7, ...)
τ_pd = propagation delay per stage [s]

Input: { n_stages, tau_pd_s }
Returns: { ok, freq_hz, period_s, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "n_stages": {
      "type": "integer",
      "description": "Number of inverter stages (odd integer \u2265 3).",
      "minimum": 3
    },
    "tau_pd_s": {
      "type": "number",
      "description": "Propagation delay per stage [s], e.g. 50e-12 for 50 ps."
    }
  },
  "required": [
    "n_stages",
    "tau_pd_s"
  ]
}
```

---

## `pll_divider_n`

Compute PLL feedback divider N from desired output and reference frequencies.

Integer-N: N = round(f_out / f_ref); actual f_out = N × f_ref
Fractional-N: N = f_out / f_ref (exact float)

Input: { f_out_hz, f_ref_hz, integer_n? }
Returns: { ok, N_exact, N_used, f_out_actual_hz, freq_error_ppm, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f_out_hz": {
      "type": "number",
      "description": "Desired VCO output frequency [Hz]."
    },
    "f_ref_hz": {
      "type": "number",
      "description": "PFD reference frequency [Hz]."
    },
    "integer_n": {
      "type": "boolean",
      "description": "True for integer-N PLL (default), False for fractional-N."
    }
  },
  "required": [
    "f_out_hz",
    "f_ref_hz"
  ]
}
```

---

## `pll_loop_filter`

Design a type-II charge-pump PLL loop filter (2nd or 3rd order).

Model (Banerjee 'PLL Performance, Simulation, and Design' 5e, 2006):
  C1 = Icp × Kvco / (2π × N × ωn²)
  R  = 2ζ / (ωn × C1)
  C2 = C1 / 10   [reference spur suppression]

ζ from phase margin φm (Banerjee approximation):
  ζ = tan(φm)/2 + sqrt(tan²(φm)/4 + 1)/2

Stability: phase margin < 45° → UNSTABLE.

Input: { f_loop_bw_hz, phase_margin_deg, icp_a, kvco_hz_per_v, n_divider, order? }
Returns: { ok, R_ohm, C1_f, C2_f, zeta, omega_n_rad_s, stable, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f_loop_bw_hz": {
      "type": "number",
      "description": "Loop bandwidth [Hz]."
    },
    "phase_margin_deg": {
      "type": "number",
      "description": "Desired phase margin [degrees] (45\u201370\u00b0 typical)."
    },
    "icp_a": {
      "type": "number",
      "description": "Charge pump current [A], e.g. 1e-3 (1 mA)."
    },
    "kvco_hz_per_v": {
      "type": "number",
      "description": "VCO gain [Hz/V], e.g. 50e6 (50 MHz/V)."
    },
    "n_divider": {
      "type": "number",
      "description": "Feedback divider ratio N."
    },
    "order": {
      "type": "integer",
      "enum": [
        2,
        3
      ],
      "description": "Loop filter order: 2 (default) or 3."
    }
  },
  "required": [
    "f_loop_bw_hz",
    "phase_margin_deg",
    "icp_a",
    "kvco_hz_per_v",
    "n_divider"
  ]
}
```

---

## `pll_lock_time`

Estimate PLL acquisition lock time for a frequency step.

Model (Banerjee 2006 §3.8 / Gardner 2005):
  t_lock ≈ −ln(ε_freq / f_step) / (ζ × ωn)

Valid for type-II 2nd-order PLL in the linear range (no cycle-slip).

Input: { f_loop_bw_hz, zeta, f_step_hz, epsilon_hz? }
Returns: { ok, t_lock_s, t_lock_us }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f_loop_bw_hz": {
      "type": "number",
      "description": "Loop bandwidth [Hz]."
    },
    "zeta": {
      "type": "number",
      "description": "Damping ratio (from loop filter design)."
    },
    "f_step_hz": {
      "type": "number",
      "description": "Frequency step size [Hz]."
    },
    "epsilon_hz": {
      "type": "number",
      "description": "Frequency accuracy at lock [Hz] (default 1.0 Hz)."
    }
  },
  "required": [
    "f_loop_bw_hz",
    "zeta",
    "f_step_hz"
  ]
}
```

---

## `pll_phase_noise_to_jitter`

Convert single-sideband phase noise to integrated RMS jitter.

Approximation for flat phase-noise floor L(f) [dBc/Hz] over bandwidth BW:
  L_lin = 10^(L_dBc/10)
  σ_phase [rad] = sqrt(2 × L_lin × BW)
  σ_jitter [s]  = σ_phase / (2π × f_osc)

Reference spurs are NOT included (see ref_spur_note in response).

Input: { f_osc_hz, phase_noise_dbc_hz, integration_bw_hz }
Returns: { ok, sigma_jitter_s, sigma_jitter_ps, sigma_jitter_fs, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f_osc_hz": {
      "type": "number",
      "description": "Oscillator frequency [Hz]."
    },
    "phase_noise_dbc_hz": {
      "type": "number",
      "description": "Phase noise spectral density [dBc/Hz] (typically negative, e.g. \u2212130 for a good 100 MHz TCXO)."
    },
    "integration_bw_hz": {
      "type": "number",
      "description": "One-sided integration bandwidth [Hz]."
    }
  },
  "required": [
    "f_osc_hz",
    "phase_noise_dbc_hz",
    "integration_bw_hz"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
