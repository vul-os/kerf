# thermoelectric

*Module: `kerf_electronics.thermoelectric.tools` · Domain: electronics*

This module registers **11** LLM tool(s):

- [`tec_figure_of_merit`](#tec-figure-of-merit)
- [`tec_operating_point`](#tec-operating-point)
- [`tec_optimal_current`](#tec-optimal-current)
- [`tec_delta_t_max`](#tec-delta-t-max)
- [`tec_couples_required`](#tec-couples-required)
- [`tec_heatsink_coupled`](#tec-heatsink-coupled)
- [`tec_multistage`](#tec-multistage)
- [`teg_output`](#teg-output)
- [`teg_efficiency`](#teg-efficiency)
- [`teg_array`](#teg-array)
- [`teg_fill_factor`](#teg-fill-factor)

---

## `tec_figure_of_merit`

Compute the thermoelectric figure of merit Z [1/K] and dimensionless ZT for a thermoelectric couple.

Z = α² / (R · K)
ZT = Z · T_mean   (requires t_mean)

where:
  α   — Seebeck coefficient [V/K]  (n+p couple pair total)
  R   — electrical resistance of the couple [Ω]
  K   — thermal conductance of the couple [W/K]
  T   — mean absolute temperature [K]

Input: { alpha, resistance, thermal_conductance, t_mean? }
Returns: { ok, Z, ZT, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient [V/K] of the couple (n+p pair total)."
    },
    "resistance": {
      "type": "number",
      "description": "Electrical resistance of the couple [\u03a9]."
    },
    "thermal_conductance": {
      "type": "number",
      "description": "Thermal conductance of the couple [W/K]."
    },
    "t_mean": {
      "type": "number",
      "description": "Mean absolute temperature [K] (required to compute ZT; optional for Z only)."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "thermal_conductance"
  ]
}
```

---

## `tec_operating_point`

Compute the steady-state operating point of a Peltier TEC module.

Equations (Goldsmid 2009 §4):
  Qc = α·I·Tc − ½·I²·R − K·ΔT
  Qh = α·I·Th + ½·I²·R − K·ΔT
  P  = Qh − Qc
  COP = Qc / P

A warning is issued when Qc < 0 (module cannot pump heat at this point).

Input: { alpha, resistance, thermal_conductance, current, tc, th }
Returns: { ok, Qc, Qh, P_input, COP, delta_T, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient [V/K]."
    },
    "resistance": {
      "type": "number",
      "description": "Module resistance [\u03a9]."
    },
    "thermal_conductance": {
      "type": "number",
      "description": "Module thermal conductance [W/K]."
    },
    "current": {
      "type": "number",
      "description": "Drive current [A]."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side absolute temperature [K]."
    },
    "th": {
      "type": "number",
      "description": "Hot-side absolute temperature [K]."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "thermal_conductance",
    "current",
    "tc",
    "th"
  ]
}
```

---

## `tec_optimal_current`

Compute optimal drive currents for a Peltier TEC module.

I_max_Qc  — current maximising cold-side heat pumping:
  I_max_Qc = α·Tc / R

I_max_COP — current maximising coefficient of performance (Ioffe 1957):
  I_max_COP = α·ΔT / (R·(√(1+Z·Tmean) − 1))
  COP_max   = (Tc/ΔT) · (M − Th/Tc) / (M + 1)
  where M = √(1 + Z·Tmean)

Input: { alpha, resistance, thermal_conductance, tc, th }
Returns: { ok, I_max_Qc, Qc_at_I_max_Qc, I_max_COP, COP_max, Z, ZT_mean, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient [V/K]."
    },
    "resistance": {
      "type": "number",
      "description": "Module resistance [\u03a9]."
    },
    "thermal_conductance": {
      "type": "number",
      "description": "Module thermal conductance [W/K]."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side absolute temperature [K]."
    },
    "th": {
      "type": "number",
      "description": "Hot-side absolute temperature [K]."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "thermal_conductance",
    "tc",
    "th"
  ]
}
```

---

## `tec_delta_t_max`

Compute the maximum achievable temperature difference (ΔT_max) of a single-stage TEC module at zero heat load.

ΔT_max = ½ · Z · Tc²    where Z = α² / (R·K)
Th_max  = Tc + ΔT_max

This is the theoretical upper bound for a single-stage module with no cooling load on the cold side.

Input: { alpha, resistance, thermal_conductance, tc }
Returns: { ok, delta_T_max, Th_max, Z, tc }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient [V/K]."
    },
    "resistance": {
      "type": "number",
      "description": "Module resistance [\u03a9]."
    },
    "thermal_conductance": {
      "type": "number",
      "description": "Module thermal conductance [W/K]."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side absolute temperature [K]."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "thermal_conductance",
    "tc"
  ]
}
```

---

## `tec_couples_required`

Determine the minimum number of thermoelectric couples N needed to achieve a target cold-side heat pumping rate Qc_target [W].

Scales Qc linearly with N:  Qc_total = N · Qc_per_couple.
Returns N = ceil(Qc_target / Qc_per_couple).
Issues a warning when Qc_per_couple ≤ 0 (impossible at this ΔT/current).

Input: { alpha_per_couple, resistance_per_couple, thermal_conductance_per_couple, current, tc, th, Qc_target }
Returns: { ok, N, Qc_per_couple, Qc_total, Qh_total, P_total, COP, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha_per_couple": {
      "type": "number",
      "description": "Seebeck coefficient per couple [V/K]."
    },
    "resistance_per_couple": {
      "type": "number",
      "description": "Resistance per couple [\u03a9]."
    },
    "thermal_conductance_per_couple": {
      "type": "number",
      "description": "Thermal conductance per couple [W/K]."
    },
    "current": {
      "type": "number",
      "description": "Drive current [A]."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side temperature [K]."
    },
    "th": {
      "type": "number",
      "description": "Hot-side temperature [K]."
    },
    "Qc_target": {
      "type": "number",
      "description": "Required cold-side heat pumping [W]."
    }
  },
  "required": [
    "alpha_per_couple",
    "resistance_per_couple",
    "thermal_conductance_per_couple",
    "current",
    "tc",
    "th",
    "Qc_target"
  ]
}
```

---

## `tec_heatsink_coupled`

Solve for the hot-side temperature Th of a TEC coupled to a heatsink with thermal resistance Rθ [K/W] to ambient.

Equilibrium:  Th = T_ambient + Rθ · Qh(Th)

Solved by fixed-point iteration (up to 200 steps).
Issues a warning when the iteration does not converge (heatsink undersized) or when Qc < 0 (negative heat pumping).

Input: { alpha, resistance, thermal_conductance, current, tc, t_ambient, rtheta }
Returns: { ok, Th, Qc, Qh, P_input, COP, delta_T, converged, iterations, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient [V/K]."
    },
    "resistance": {
      "type": "number",
      "description": "Module resistance [\u03a9]."
    },
    "thermal_conductance": {
      "type": "number",
      "description": "Module thermal conductance [W/K]."
    },
    "current": {
      "type": "number",
      "description": "Drive current [A]."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side (object) temperature [K]."
    },
    "t_ambient": {
      "type": "number",
      "description": "Ambient (heatsink inlet) temperature [K]."
    },
    "rtheta": {
      "type": "number",
      "description": "Heatsink thermal resistance [K/W]."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "thermal_conductance",
    "current",
    "tc",
    "t_ambient",
    "rtheta"
  ]
}
```

---

## `tec_multistage`

Design a multistage (cascade) TEC for large ΔT that exceeds a single module's ΔT_max.

Each stage is described by its own parameters; the hot side of stage n feeds the cold side of stage n+1.  ΔT is distributed evenly among stages.

Input: { stages: [{alpha, resistance, thermal_conductance, current}, ...], t_cold_target, t_hot_ambient }
Returns: { ok, stages_results, total_delta_T, Tc_final, Th_final, warnings }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "stages": {
      "type": "array",
      "description": "List of stage parameter dicts [{alpha, resistance, thermal_conductance, current}].",
      "items": {
        "type": "object",
        "properties": {
          "alpha": {
            "type": "number"
          },
          "resistance": {
            "type": "number"
          },
          "thermal_conductance": {
            "type": "number"
          },
          "current": {
            "type": "number"
          }
        },
        "required": [
          "alpha",
          "resistance",
          "thermal_conductance",
          "current"
        ]
      }
    },
    "t_cold_target": {
      "type": "number",
      "description": "Desired cold-side temperature [K]."
    },
    "t_hot_ambient": {
      "type": "number",
      "description": "Hot-side ambient temperature [K]."
    }
  },
  "required": [
    "stages",
    "t_cold_target",
    "t_hot_ambient"
  ]
}
```

---

## `teg_output`

Compute TEG (Seebeck generator) output: open-circuit voltage, matched-load power, current, voltage, and arbitrary-load operating point.

Equations (Rowe 1995 §2; Goldsmid 2009 §5):
  Voc = α·N·ΔT        — open-circuit voltage
  Ri  = N·R            — internal resistance
  Im  = Voc / (2·Ri)  — matched-load current  (R_load = Ri)
  Pm  = Voc² / (4·Ri) — matched-load power

Carnot efficiency: ηC = ΔT / Th

Input: { alpha, resistance, n_couples, tc, th, r_load? }
Returns: { ok, Voc, Ri, Im, Vm, Pm, I_load, V_load, P_load, eta_carnot, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient per couple [V/K]."
    },
    "resistance": {
      "type": "number",
      "description": "Electrical resistance per couple [\u03a9]."
    },
    "n_couples": {
      "type": "integer",
      "description": "Number of thermoelectric couples."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side temperature [K]."
    },
    "th": {
      "type": "number",
      "description": "Hot-side temperature [K]."
    },
    "r_load": {
      "type": "number",
      "description": "Load resistance [\u03a9]; omit for matched-load (R_load = Ri)."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "n_couples",
    "tc",
    "th"
  ]
}
```

---

## `teg_efficiency`

Compute TEG maximum efficiency and optimal load resistance for the max-η operating point.

ηmax = (ΔT/Th) · (M − 1) / (M + Tc/Th)    (Ioffe / Goldsmid)
ηC   = ΔT / Th                               (Carnot)
M    = √(1 + Z·Tmean)
R_opt = R · M   (per couple, for max-η)

Input: { alpha, resistance, thermal_conductance, tc, th }
Returns: { ok, eta_max, eta_carnot, eta_ratio, Z, ZT_mean, M, R_opt_per_couple, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient per couple [V/K]."
    },
    "resistance": {
      "type": "number",
      "description": "Resistance per couple [\u03a9]."
    },
    "thermal_conductance": {
      "type": "number",
      "description": "Thermal conductance per couple [W/K]."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side temperature [K]."
    },
    "th": {
      "type": "number",
      "description": "Hot-side temperature [K]."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "thermal_conductance",
    "tc",
    "th"
  ]
}
```

---

## `teg_array`

Compute output of a TEG module array with Ns modules in series and Np modules in parallel.

Series increases voltage; parallel increases current:
  Varray = Ns · Voc_module
  Iarray = Np · Im_module
  Parray = Ns · Np · Pm_module

Input: { alpha, resistance, n_couples, tc, th, n_series, n_parallel }
Returns: { ok, Varray, Iarray, Parray, n_total_modules, Voc_module, Pm_module, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha": {
      "type": "number",
      "description": "Seebeck coefficient per couple [V/K]."
    },
    "resistance": {
      "type": "number",
      "description": "Resistance per couple [\u03a9]."
    },
    "n_couples": {
      "type": "integer",
      "description": "Number of couples per module."
    },
    "tc": {
      "type": "number",
      "description": "Cold-side temperature [K]."
    },
    "th": {
      "type": "number",
      "description": "Hot-side temperature [K]."
    },
    "n_series": {
      "type": "integer",
      "description": "Number of modules in series (Ns)."
    },
    "n_parallel": {
      "type": "integer",
      "description": "Number of modules in parallel (Np)."
    }
  },
  "required": [
    "alpha",
    "resistance",
    "n_couples",
    "tc",
    "th",
    "n_series",
    "n_parallel"
  ]
}
```

---

## `teg_fill_factor`

Compute the fill factor of a TEG module.

FF = (total pellet cross-section area) / (module footprint area)

A higher FF means more active thermoelectric area and higher effective Z. Warns if FF > 1 (geometry inputs inconsistent).

Input: { pellet_area_mm2, pellet_height_mm, n_couples, module_footprint_mm2 }
Returns: { ok, fill_factor, total_pellet_area_mm2, n_legs, ... }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pellet_area_mm2": {
      "type": "number",
      "description": "Cross-section area of one pellet leg [mm\u00b2]."
    },
    "pellet_height_mm": {
      "type": "number",
      "description": "Pellet height (leg length) [mm]."
    },
    "n_couples": {
      "type": "integer",
      "description": "Number of couples (n + p leg pairs)."
    },
    "module_footprint_mm2": {
      "type": "number",
      "description": "Module footprint area [mm\u00b2]."
    }
  },
  "required": [
    "pellet_area_mm2",
    "pellet_height_mm",
    "n_couples",
    "module_footprint_mm2"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
