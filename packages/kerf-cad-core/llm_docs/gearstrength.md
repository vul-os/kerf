# gearstrength

*Module: `kerf_cad_core.gearstrength.tools` · Domain: cad*

This module registers **16** LLM tool(s):

- [`agma_dynamic_factor`](#agma-dynamic-factor)
- [`agma_geometry_factor_J`](#agma-geometry-factor-J)
- [`agma_geometry_factor_I`](#agma-geometry-factor-I)
- [`agma_bending_stress`](#agma-bending-stress)
- [`agma_contact_stress`](#agma-contact-stress)
- [`agma_safety_factors`](#agma-safety-factors)
- [`agma_power_rating`](#agma-power-rating)
- [`agma_service_life`](#agma-service-life)
- [`iso6336_dynamic_factor`](#iso6336-dynamic-factor)
- [`iso6336_geometry_factor_YF`](#iso6336-geometry-factor-YF)
- [`iso6336_helix_factor`](#iso6336-helix-factor)
- [`iso6336_zone_factor`](#iso6336-zone-factor)
- [`iso6336_elasticity_factor`](#iso6336-elasticity-factor)
- [`iso6336_bending_stress`](#iso6336-bending-stress)
- [`iso6336_contact_stress`](#iso6336-contact-stress)
- [`iso6336_safety_factors`](#iso6336-safety-factors)

---

## `agma_dynamic_factor`

Compute the AGMA dynamic factor Kv from quality number Qv and pitch-line velocity (ft/min).

Kv >= 1 amplifies the transmitted load Wt to account for dynamic tooth loads caused by gear errors and inertia.  Higher Qv (better quality) reduces Kv.

Pitch-line velocity: Vt_fpm = π · d_in · n_rpm / 12.

Returns Kv, validity range, and a warning if velocity exceeds the AGMA limit for the chosen quality number.

Reference: AGMA 2001-D04 §6.2; Shigley 10th §14-2 Eqs (14-27)-(14-28).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Vt_fpm": {
      "type": "number",
      "description": "Pitch-line velocity (ft/min). Must be > 0."
    },
    "Qv": {
      "type": "number",
      "description": "AGMA quality number. Range 3\u201312. Typical: hobbed 5-6, shaved 7-8, ground 11-12."
    }
  },
  "required": [
    "Vt_fpm",
    "Qv"
  ]
}
```

---

## `agma_geometry_factor_J`

Compute the AGMA bending geometry factor J for spur (ψ=0) or helical gears.

J is the Lewis form factor corrected for helical overlap.  Values are interpolated from the AGMA/Shigley Table 14-2 for 20° or 25° normal pressure angles.  A simplified helix correction is applied.

Use J in: σ_t = Wt·Ko·Kv·Ks·Km·KB / (b·m·J).

Reference: AGMA 908-B89; Shigley 10th §14-3 Table 14-2.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "N": {
      "type": "number",
      "description": "Number of teeth on the gear. Must be >= 12."
    },
    "psi_deg": {
      "type": "number",
      "description": "Helix angle (degrees). 0 = spur; helical typically 15\u201330\u00b0."
    },
    "pressure_angle_deg": {
      "type": "number",
      "description": "Normal pressure angle (degrees). Default 20; supported 14\u201330."
    }
  },
  "required": [
    "N",
    "psi_deg"
  ]
}
```

---

## `agma_geometry_factor_I`

Compute the AGMA pitting (contact) geometry factor I for a gear pair.

I accounts for the geometry of contact between the mating flanks. Used in: σ_c = Cp · √(Wt·Ko·Kv·Ks·Km / (d·b·I)).

Supply the pinion as N_p (smaller gear, N_p <= N_g).

Reference: Shigley 10th §14-3, Eq. (14-23).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "N_p": {
      "type": "number",
      "description": "Number of teeth on pinion (smaller gear). >= 12."
    },
    "N_g": {
      "type": "number",
      "description": "Number of teeth on gear (larger gear). >= N_p."
    },
    "psi_deg": {
      "type": "number",
      "description": "Helix angle (degrees). 0 = spur."
    },
    "pressure_angle_deg": {
      "type": "number",
      "description": "Normal pressure angle (degrees). Default 20."
    },
    "external": {
      "type": "boolean",
      "description": "True (default) = external mesh; False = internal ring gear."
    }
  },
  "required": [
    "N_p",
    "N_g",
    "psi_deg"
  ]
}
```

---

## `agma_bending_stress`

Compute the AGMA 2001-D04 bending stress σ_t.

Metric:   σ_t = Wt·Ko·Kv·Ks·Km·KB / (b·m·J)   [MPa]
English:  σ_t = Wt·Ko·Kv·Ks·Pd·Km·KB / (b·J)   [psi]

Use metric=true for SI units (N, mm, MPa), metric=false (default) for English (lbf, in, psi).

Reference: AGMA 2001-D04 §6.1; Shigley 10th Eq. (14-15).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Wt": {
      "type": "number",
      "description": "Tangential transmitted load. lbf (English) or N (metric)."
    },
    "Ko": {
      "type": "number",
      "description": "Overload factor (>= 1). Accounts for external dynamic loads."
    },
    "Kv": {
      "type": "number",
      "description": "Dynamic factor (>= 1). From agma_dynamic_factor."
    },
    "Ks": {
      "type": "number",
      "description": "Size factor (>= 1; typically 1.0 for Pd >= 5)."
    },
    "Km": {
      "type": "number",
      "description": "Load-distribution factor (>= 1)."
    },
    "KB": {
      "type": "number",
      "description": "Rim thickness factor (1.0 for solid blank)."
    },
    "b": {
      "type": "number",
      "description": "Face width. in (English) or mm (metric)."
    },
    "m_or_Pd": {
      "type": "number",
      "description": "Module m [mm] (metric) or diametral pitch Pd [teeth/in] (English)."
    },
    "J": {
      "type": "number",
      "description": "Bending geometry factor from agma_geometry_factor_J."
    },
    "metric": {
      "type": "boolean",
      "description": "True = metric (N/mm/MPa); False = English (lbf/in/psi). Default false."
    }
  },
  "required": [
    "Wt",
    "Ko",
    "Kv",
    "Ks",
    "Km",
    "KB",
    "b",
    "m_or_Pd",
    "J"
  ]
}
```

---

## `agma_contact_stress`

Compute the AGMA 2001-D04 contact (pitting) stress σ_c.

σ_c = Cp · √(Wt·Ko·Kv·Ks·Km / (d_p·b·I))

Cp (elastic coefficient):
  Steel/steel English: 2300 √psi
  Steel/steel metric:  191 √MPa

Reference: AGMA 2001-D04 §6.2; Shigley 10th Eq. (14-16).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Wt": {
      "type": "number",
      "description": "Tangential transmitted load. lbf or N."
    },
    "Ko": {
      "type": "number",
      "description": "Overload factor (>= 1)."
    },
    "Kv": {
      "type": "number",
      "description": "Dynamic factor (>= 1)."
    },
    "Ks": {
      "type": "number",
      "description": "Size factor (>= 1)."
    },
    "Km": {
      "type": "number",
      "description": "Load-distribution factor (>= 1)."
    },
    "Cp": {
      "type": "number",
      "description": "Elastic coefficient. Steel/steel: 2300 \u221apsi (English) or 191 \u221aMPa (metric)."
    },
    "d_p": {
      "type": "number",
      "description": "Pinion pitch diameter. in (English) or mm (metric)."
    },
    "b": {
      "type": "number",
      "description": "Face width. in or mm."
    },
    "I": {
      "type": "number",
      "description": "Pitting geometry factor from agma_geometry_factor_I."
    },
    "metric": {
      "type": "boolean",
      "description": "True = metric (N/mm/MPa). Default false."
    }
  },
  "required": [
    "Wt",
    "Ko",
    "Kv",
    "Ks",
    "Km",
    "Cp",
    "d_p",
    "b",
    "I"
  ]
}
```

---

## `agma_safety_factors`

Compute AGMA 2001-D04 safety factors SF (bending) and SH (contact).

Allowable bending stress: sigma_t_all = S_t · YN / (K_T · K_R)
Allowable contact stress: sigma_c_all = S_c · ZN / (K_T · K_R)
SF = sigma_t_all / sigma_b  (>= 1 required; >= 1.2 recommended)
SH = sigma_c_all / sigma_c  (>= 1 required; >= 1.2 recommended)

Reference: AGMA 2001-D04 §4.1; Shigley 10th §14-5.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sigma_b": {
      "type": "number",
      "description": "Actual AGMA bending stress \u03c3_t (psi or MPa)."
    },
    "sigma_c": {
      "type": "number",
      "description": "Actual AGMA contact stress \u03c3_c (psi or MPa)."
    },
    "S_t": {
      "type": "number",
      "description": "Allowable bending stress number (material, psi or MPa). Typical carburised steel: 65 kpsi / 450 MPa."
    },
    "S_c": {
      "type": "number",
      "description": "Allowable contact stress number (material, psi or MPa). Typical carburised steel: 225 kpsi / 1550 MPa."
    },
    "YN": {
      "type": "number",
      "description": "Bending stress-cycle factor (default 1.0)."
    },
    "ZN": {
      "type": "number",
      "description": "Contact stress-cycle factor (default 1.0)."
    },
    "K_T": {
      "type": "number",
      "description": "Temperature factor (default 1.0 for T < 120\u00b0C)."
    },
    "K_R": {
      "type": "number",
      "description": "Reliability factor (1.0 \u2192 90%, 1.25 \u2192 99%). Default 1.0."
    }
  },
  "required": [
    "sigma_b",
    "sigma_c",
    "S_t",
    "S_c"
  ]
}
```

---

## `agma_power_rating`

Compute the maximum safe transmitted power and torque for a gear pair based on AGMA 2001-D04 allowable stresses.

Solves for the governing tangential load Wt from both bending and contact allowable stress limits, then converts to power (hp or kW) and torque.

Use metric=true for SI (N, mm, kW, MPa), default is English (lbf, in, hp, psi).

Reference: AGMA 2001-D04; Shigley 10th §14-5.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "S_t": {
      "type": "number",
      "description": "Allowable bending stress number (psi or MPa)."
    },
    "S_c": {
      "type": "number",
      "description": "Allowable contact stress number (psi or MPa)."
    },
    "Cp": {
      "type": "number",
      "description": "Elastic coefficient. Steel/steel: 2300 \u221apsi or 191 \u221aMPa."
    },
    "b": {
      "type": "number",
      "description": "Face width. in or mm."
    },
    "m_or_Pd": {
      "type": "number",
      "description": "Module m [mm] or diametral pitch Pd [1/in]."
    },
    "d_p": {
      "type": "number",
      "description": "Pinion pitch diameter. in or mm."
    },
    "N_p": {
      "type": "number",
      "description": "Pinion tooth count."
    },
    "N_g": {
      "type": "number",
      "description": "Gear tooth count (>= N_p)."
    },
    "psi_deg": {
      "type": "number",
      "description": "Helix angle (deg). 0 = spur."
    },
    "n_rpm": {
      "type": "number",
      "description": "Pinion rotational speed (rpm)."
    },
    "metric": {
      "type": "boolean",
      "description": "True = SI units. Default false."
    },
    "Ko": {
      "type": "number",
      "description": "Overload factor. Default 1.0."
    },
    "Ks": {
      "type": "number",
      "description": "Size factor. Default 1.0."
    },
    "Km": {
      "type": "number",
      "description": "Load-distribution factor. Default 1.3."
    },
    "KB": {
      "type": "number",
      "description": "Rim thickness factor. Default 1.0."
    },
    "Qv": {
      "type": "number",
      "description": "AGMA quality number (3\u201312). Default 6."
    },
    "K_T": {
      "type": "number",
      "description": "Temperature factor. Default 1.0."
    },
    "K_R": {
      "type": "number",
      "description": "Reliability factor. Default 1.0."
    },
    "pressure_angle_deg": {
      "type": "number",
      "description": "Normal pressure angle. Default 20."
    },
    "YN": {
      "type": "number",
      "description": "Bending cycle factor. Default 1.0."
    },
    "ZN": {
      "type": "number",
      "description": "Contact cycle factor. Default 1.0."
    }
  },
  "required": [
    "S_t",
    "S_c",
    "Cp",
    "b",
    "m_or_Pd",
    "d_p",
    "N_p",
    "N_g",
    "psi_deg",
    "n_rpm"
  ]
}
```

---

## `agma_service_life`

Compute AGMA 2001-D04 stress-cycle factors YN (bending) and ZN (contact) for a given number of stress cycles.

YN and ZN scale the allowable stresses for finite service life:
  sigma_t_all = S_t · YN / (K_T · K_R)
  sigma_c_all = S_c · ZN / (K_T · K_R)

At very long life both approach ~0.9 (conservative AGMA plateau).

Cycles for a rotating gear: N = n_rpm × 60 × hours.

Reference: AGMA 2001-D04 §§ 4.2.1-4.2.2; Shigley 10th Eqs. (14-31)-(14-35).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "N_cycles": {
      "type": "number",
      "description": "Number of stress cycles. Must be > 0."
    },
    "hardness_HB": {
      "type": "number",
      "description": "Brinell hardness HB (default 200). Through-hardened valid range: 180\u2013400 HB."
    },
    "gear_type": {
      "type": "string",
      "enum": [
        "through_hardened"
      ],
      "description": "Gear heat-treatment type. Currently: through_hardened."
    }
  },
  "required": [
    "N_cycles"
  ]
}
```

---

## `iso6336_dynamic_factor`

Compute the ISO 6336-1:2019 dynamic factor Kv (Method B) for spur or helical gears.

Kv accounts for mesh-induced dynamic loads from pitch errors and tooth elasticity. Method B uses pitch-line velocity and ISO quality grade (1328-1). Sub/main-resonance/super-critical branches selected automatically based on resonance speed estimate.

Reference: ISO 6336-1:2019 §6.5 Method B, Eqs. (62)–(73).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "v_ms": {
      "type": "number",
      "description": "Pitch-line velocity (m/s). Must be > 0."
    },
    "z1": {
      "type": "number",
      "description": "Pinion tooth count. Must be >= 5."
    },
    "m_n_mm": {
      "type": "number",
      "description": "Normal module (mm). Must be > 0."
    },
    "quality": {
      "type": "number",
      "description": "ISO 1328-1 quality grade (4\u201312). Default 6."
    },
    "bearing_distance_mm": {
      "type": "number",
      "description": "Bearing span (mm). Default 100."
    },
    "pinion_shaft_dia_mm": {
      "type": "number",
      "description": "Shaft diameter (mm). Default 40."
    }
  },
  "required": [
    "v_ms",
    "z1",
    "m_n_mm"
  ]
}
```

---

## `iso6336_geometry_factor_YF`

Compute the ISO 6336-3:2019 tooth form factor YF (Method B) for root bending strength.

YF = (6·hFe/m_n · cos(alpha_Fen)) / (sFn/m_n)^2 · cos(alpha_n)

Accounts for tooth geometry, profile shift, and basic rack parameters.

Reference: ISO 6336-3:2019 §5.3, Eqs. (4)–(22).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "z": {
      "type": "number",
      "description": "Number of teeth. Must be >= 5."
    },
    "x": {
      "type": "number",
      "description": "Profile shift coefficient (\u22120.7 to +0.7)."
    },
    "alpha_n_deg": {
      "type": "number",
      "description": "Normal pressure angle (degrees). Default 20."
    },
    "haP_star": {
      "type": "number",
      "description": "Addendum coefficient (default 1.0)."
    },
    "hfP_star": {
      "type": "number",
      "description": "Dedendum coefficient (default 1.25)."
    },
    "rhoFP_star": {
      "type": "number",
      "description": "Root fillet radius coefficient (default 0.38)."
    }
  },
  "required": [
    "z",
    "x"
  ]
}
```

---

## `iso6336_helix_factor`

Compute ISO 6336 helix factors Ybeta (bending, ISO 6336-3 §5.4) and Zbeta (contact, ISO 6336-2 §5.3) from the reference helix angle.

Ybeta = 1 − eps_beta·beta_b/120  (reduces bending stress for helical)
Zbeta = 1/sqrt(cos(beta))         (increases contact capacity)

For spur gears (beta=0): Ybeta=1, Zbeta=1.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "beta_deg": {
      "type": "number",
      "description": "Helix angle (degrees). 0 = spur."
    }
  },
  "required": [
    "beta_deg"
  ]
}
```

---

## `iso6336_zone_factor`

Compute the ISO 6336-2:2019 zone factor ZH for Hertzian contact pressure at the pitch point.

ZH = sqrt(2·cos(beta_b)·cos(alpha_wt)) / (cos²(alpha_t)·sin(alpha_wt))

For steel spur gears with 20° pressure angle: ZH ≈ 2.495.

Reference: ISO 6336-2:2019 §5.2, Eq. (4).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha_n_deg": {
      "type": "number",
      "description": "Normal pressure angle (degrees)."
    },
    "beta_deg": {
      "type": "number",
      "description": "Helix angle (degrees). 0 = spur."
    },
    "alpha_wt_deg": {
      "type": "number",
      "description": "Working transverse pressure angle (degrees; optional)."
    },
    "z1": {
      "type": "number",
      "description": "Pinion tooth count (for profile-shift alpha_wt calc)."
    },
    "z2": {
      "type": "number",
      "description": "Gear tooth count (for profile-shift alpha_wt calc)."
    },
    "x1": {
      "type": "number",
      "description": "Pinion profile shift coefficient. Default 0."
    },
    "x2": {
      "type": "number",
      "description": "Gear profile shift coefficient. Default 0."
    }
  },
  "required": [
    "alpha_n_deg",
    "beta_deg"
  ]
}
```

---

## `iso6336_elasticity_factor`

Compute ISO 6336-2:2019 elasticity factor ZE [sqrt(MPa)] for Hertzian contact stress.

ZE = sqrt(1 / (pi · ((1-nu1²)/E1 + (1-nu2²)/E2)))

Steel/steel (E=206000 MPa, nu=0.3): ZE = 191 sqrt(MPa).

Reference: ISO 6336-2:2019 §5.3, Eq. (7).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "E1_MPa": {
      "type": "number",
      "description": "Young's modulus of pinion (MPa)."
    },
    "nu1": {
      "type": "number",
      "description": "Poisson's ratio of pinion (0\u20130.5)."
    },
    "E2_MPa": {
      "type": "number",
      "description": "Young's modulus of gear (MPa)."
    },
    "nu2": {
      "type": "number",
      "description": "Poisson's ratio of gear (0\u20130.5)."
    }
  },
  "required": [
    "E1_MPa",
    "nu1",
    "E2_MPa",
    "nu2"
  ]
}
```

---

## `iso6336_bending_stress`

Compute ISO 6336-3:2019 root bending stress sigma_F.

sigma_F0 = Ft / (b·m_n) · YF · YS · Ybeta       [MPa, nominal]
sigma_F  = sigma_F0 · KA · Kv · KFbeta · KFalpha · Ydelta  [MPa]

Requires pre-computed factors from iso6336_geometry_factor_YF, iso6336_helix_factor, iso6336_dynamic_factor, and iso6336_load_distribution_bending.

Reference: ISO 6336-3:2019 §5, Eqs. (1)–(3).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Ft_N": {
      "type": "number",
      "description": "Tangential mesh force (N)."
    },
    "b_mm": {
      "type": "number",
      "description": "Face width (mm)."
    },
    "m_n_mm": {
      "type": "number",
      "description": "Normal module (mm)."
    },
    "KA": {
      "type": "number",
      "description": "Application factor (>= 1)."
    },
    "Kv": {
      "type": "number",
      "description": "Dynamic factor (>= 1)."
    },
    "KFbeta": {
      "type": "number",
      "description": "Face load factor for bending (>= 1)."
    },
    "KFalpha": {
      "type": "number",
      "description": "Transverse load factor for bending (>= 1)."
    },
    "YF": {
      "type": "number",
      "description": "Tooth form factor from iso6336_geometry_factor_YF."
    },
    "Ybeta": {
      "type": "number",
      "description": "Helix factor from iso6336_helix_factor."
    },
    "YS": {
      "type": "number",
      "description": "Stress correction factor (default 1.0)."
    },
    "Ydelta": {
      "type": "number",
      "description": "Notch sensitivity factor (default 1.0)."
    }
  },
  "required": [
    "Ft_N",
    "b_mm",
    "m_n_mm",
    "KA",
    "Kv",
    "KFbeta",
    "KFalpha",
    "YF",
    "Ybeta"
  ]
}
```

---

## `iso6336_contact_stress`

Compute ISO 6336-2:2019 pitting (contact) stress sigma_H.

sigma_H0 = ZH·ZE·Zepsilon·Zbeta·sqrt(Ft/(b·d1)·(u+1)/u)  [MPa]
sigma_H  = sigma_H0 · sqrt(KA·Kv·KHbeta·KHalpha)          [MPa]

Reference: ISO 6336-2:2019 §5, Eqs. (1)–(3).

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Ft_N": {
      "type": "number",
      "description": "Tangential mesh force (N)."
    },
    "b_mm": {
      "type": "number",
      "description": "Face width (mm)."
    },
    "d1_mm": {
      "type": "number",
      "description": "Pinion reference diameter (mm)."
    },
    "u": {
      "type": "number",
      "description": "Gear ratio z2/z1 (>= 1)."
    },
    "KA": {
      "type": "number",
      "description": "Application factor."
    },
    "Kv": {
      "type": "number",
      "description": "Dynamic factor."
    },
    "KHbeta": {
      "type": "number",
      "description": "Face load factor for contact."
    },
    "KHalpha": {
      "type": "number",
      "description": "Transverse load factor for contact."
    },
    "ZH": {
      "type": "number",
      "description": "Zone factor from iso6336_zone_factor."
    },
    "ZE": {
      "type": "number",
      "description": "Elasticity factor [sqrt(MPa)]."
    },
    "Zepsilon": {
      "type": "number",
      "description": "Contact-ratio factor."
    },
    "Zbeta": {
      "type": "number",
      "description": "Helix factor from iso6336_helix_factor."
    }
  },
  "required": [
    "Ft_N",
    "b_mm",
    "d1_mm",
    "u",
    "KA",
    "Kv",
    "KHbeta",
    "KHalpha",
    "ZH",
    "ZE",
    "Zepsilon",
    "Zbeta"
  ]
}
```

---

## `iso6336_safety_factors`

Compute ISO 6336 bending safety factor SF and pitting safety factor SH.

SF = sigma_FP / sigma_F   (>= 1.4 recommended)
SH = sigma_HP / sigma_H   (>= 1.2 recommended)

The allowable stresses sigma_FP and sigma_HP must be computed from ISO 6336-5 material data (sigma_FLim, sigma_HLim) times life factors YNT, ZNT and safety minimums SF_min, SH_min.

Reference: ISO 6336-1:2019 §4.1; ISO 6336-2:2019 §6; ISO 6336-3:2019 §6.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "sigma_F": {
      "type": "number",
      "description": "Working bending stress (MPa)."
    },
    "sigma_H": {
      "type": "number",
      "description": "Working contact stress (MPa)."
    },
    "sigma_FP": {
      "type": "number",
      "description": "Allowable bending stress (MPa)."
    },
    "sigma_HP": {
      "type": "number",
      "description": "Allowable contact stress (MPa)."
    }
  },
  "required": [
    "sigma_F",
    "sigma_H",
    "sigma_FP",
    "sigma_HP"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
