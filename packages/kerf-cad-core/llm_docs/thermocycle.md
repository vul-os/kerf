# thermocycle

*Module: `kerf_cad_core.thermocycle.tools` · Domain: cad*

This module registers **15** LLM tool(s):

- [`thermo_isentropic_relations`](#thermo-isentropic-relations)
- [`thermo_isothermal_process`](#thermo-isothermal-process)
- [`thermo_isobaric_process`](#thermo-isobaric-process)
- [`thermo_isochoric_process`](#thermo-isochoric-process)
- [`thermo_isentropic_process`](#thermo-isentropic-process)
- [`thermo_polytropic_process`](#thermo-polytropic-process)
- [`thermo_carnot_efficiency`](#thermo-carnot-efficiency)
- [`thermo_carnot_cop_refrigeration`](#thermo-carnot-cop-refrigeration)
- [`thermo_carnot_cop_heat_pump`](#thermo-carnot-cop-heat-pump)
- [`thermo_otto_cycle`](#thermo-otto-cycle)
- [`thermo_diesel_cycle`](#thermo-diesel-cycle)
- [`thermo_dual_cycle`](#thermo-dual-cycle)
- [`thermo_brayton_cycle`](#thermo-brayton-cycle)
- [`thermo_rankine_cycle_ideal`](#thermo-rankine-cycle-ideal)
- [`thermo_refrigeration_cop`](#thermo-refrigeration-cop)

---

## `thermo_isentropic_relations`

Isentropic relations for an ideal gas with constant specific-heat ratio k.

Computes unknown state-2 property from one pair of inputs:
    T2/T1 = (p2/p1)^((k-1)/k)
    T2/T1 = (v1/v2)^(k-1)
    p2/p1 = (v1/v2)^k

Provide T1, p1 and then one of: T2, p2, or (v1+v2).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T1": {
      "type": "number",
      "description": "Initial temperature (K). Must be > 0."
    },
    "p1": {
      "type": "number",
      "description": "Initial pressure (Pa). Must be > 0."
    },
    "T2": {
      "type": "number",
      "description": "Final temperature (K). Optional."
    },
    "p2": {
      "type": "number",
      "description": "Final pressure (Pa). Optional."
    },
    "v1": {
      "type": "number",
      "description": "Specific volume at state 1 (m\u00b3/kg). Optional."
    },
    "v2": {
      "type": "number",
      "description": "Specific volume at state 2 (m\u00b3/kg). Optional."
    },
    "k": {
      "type": "number",
      "description": "Specific heat ratio k (default 1.4 for air)."
    }
  },
  "required": [
    "T1",
    "p1"
  ]
}
```

---

## `thermo_isothermal_process`

Isothermal (constant-temperature) process for an ideal gas.

    p·v = const   →   p2 = p1·v1/v2
    w = p1·v1 · ln(v2/v1)   [J/kg]
    q = w   (since Δu = 0 at constant T)

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p1": {
      "type": "number",
      "description": "Initial pressure (Pa). Must be > 0."
    },
    "v1": {
      "type": "number",
      "description": "Initial specific volume (m\u00b3/kg). Must be > 0."
    },
    "v2": {
      "type": "number",
      "description": "Final specific volume (m\u00b3/kg). Must be > 0."
    },
    "T": {
      "type": "number",
      "description": "Temperature (K). Optional; used to compute R\u00b7T."
    }
  },
  "required": [
    "p1",
    "v1",
    "v2"
  ]
}
```

---

## `thermo_isobaric_process`

Isobaric (constant-pressure) process for an ideal gas.

    q  = cp · (T2 - T1)   [J/kg]
    w  = R  · (T2 - T1)   [J/kg]  (boundary work)
    Δu = cv · (T2 - T1)   [J/kg]

Default cp = 1005 J/kg·K (air). k = 1.4 assumed for deriving cv.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T1": {
      "type": "number",
      "description": "Initial temperature (K). Must be > 0."
    },
    "T2": {
      "type": "number",
      "description": "Final temperature (K). Must be > 0."
    },
    "cp": {
      "type": "number",
      "description": "Specific heat at constant pressure (J/kg\u00b7K). Default 1005 J/kg\u00b7K."
    }
  },
  "required": [
    "T1",
    "T2"
  ]
}
```

---

## `thermo_isochoric_process`

Isochoric (constant-volume) process for an ideal gas.

    q  = cv · (T2 - T1)   [J/kg]
    w  = 0                 (no boundary work)
    Δu = q

Default cv = 717.86 J/kg·K (air).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T1": {
      "type": "number",
      "description": "Initial temperature (K). Must be > 0."
    },
    "T2": {
      "type": "number",
      "description": "Final temperature (K). Must be > 0."
    },
    "cv": {
      "type": "number",
      "description": "Specific heat at constant volume (J/kg\u00b7K). Default 717.86 J/kg\u00b7K."
    }
  },
  "required": [
    "T1",
    "T2"
  ]
}
```

---

## `thermo_isentropic_process`

Isentropic (adiabatic, reversible) compression or expansion.

    T2/T1 = (p2/p1)^((k-1)/k)
    w_s   = cp · (T1 - T2)   [J/kg]  (positive = work output / expansion)
    q     = 0

Default k=1.4, cp=1005 J/kg·K (air).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T1": {
      "type": "number",
      "description": "Initial temperature (K). Must be > 0."
    },
    "p1": {
      "type": "number",
      "description": "Initial pressure (Pa). Must be > 0."
    },
    "p2": {
      "type": "number",
      "description": "Final pressure (Pa). Must be > 0."
    },
    "k": {
      "type": "number",
      "description": "Specific heat ratio (default 1.4)."
    },
    "cp": {
      "type": "number",
      "description": "cp (J/kg\u00b7K). Default 1005."
    }
  },
  "required": [
    "T1",
    "p1",
    "p2"
  ]
}
```

---

## `thermo_polytropic_process`

Polytropic process: p · v^n = const.

    p2   = p1 · (v1/v2)^n
    w    = (p2·v2 - p1·v1) / (1 - n)   [J/kg]  for n ≠ 1
    w    = p1·v1 · ln(v2/v1)            [J/kg]  for n = 1
    q    = Δu + w

Special cases: n=0 isobaric, n=1 isothermal, n=1.4 isentropic (air),
               n→∞ isochoric (use large n e.g. 1e9).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p1": {
      "type": "number",
      "description": "Initial pressure (Pa). Must be > 0."
    },
    "v1": {
      "type": "number",
      "description": "Initial specific volume (m\u00b3/kg). Must be > 0."
    },
    "v2": {
      "type": "number",
      "description": "Final specific volume (m\u00b3/kg). Must be > 0."
    },
    "n": {
      "type": "number",
      "description": "Polytropic index."
    },
    "T1": {
      "type": "number",
      "description": "Initial temperature (K). Optional; used to compute T2."
    }
  },
  "required": [
    "p1",
    "v1",
    "v2",
    "n"
  ]
}
```

---

## `thermo_carnot_efficiency`

Maximum (Carnot) thermal efficiency of a heat engine.

    η_Carnot = 1 - T_L / T_H

This is the upper bound for ANY heat engine operating between T_H and T_L.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T_H": {
      "type": "number",
      "description": "High-temperature reservoir (K). Must be > T_L > 0."
    },
    "T_L": {
      "type": "number",
      "description": "Low-temperature reservoir (K). Must be > 0."
    }
  },
  "required": [
    "T_H",
    "T_L"
  ]
}
```

---

## `thermo_carnot_cop_refrigeration`

Maximum (reverse-Carnot) COP for a refrigeration cycle.

    COP_R = T_L / (T_H - T_L)

This is the theoretical upper bound for a refrigerator between T_H and T_L.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T_H": {
      "type": "number",
      "description": "High-temperature reservoir (K). Must be > T_L > 0."
    },
    "T_L": {
      "type": "number",
      "description": "Low-temperature reservoir (K). Must be > 0."
    }
  },
  "required": [
    "T_H",
    "T_L"
  ]
}
```

---

## `thermo_carnot_cop_heat_pump`

Maximum (reverse-Carnot) COP for a heat-pump cycle.

    COP_HP = T_H / (T_H - T_L)  = 1 + COP_R

Always > 1 for T_H > T_L > 0.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T_H": {
      "type": "number",
      "description": "High-temperature reservoir (K). Must be > T_L > 0."
    },
    "T_L": {
      "type": "number",
      "description": "Low-temperature source (K). Must be > 0."
    }
  },
  "required": [
    "T_H",
    "T_L"
  ]
}
```

---

## `thermo_otto_cycle`

Air-standard Otto cycle (ideal spark-ignition engine).

    η_Otto = 1 - 1/r^(k-1)
    T2 = T1 · r^(k-1)   (end of isentropic compression)
    T4 = T3 / r^(k-1)   (end of isentropic expansion)
    w_net = cv · (T3-T2) - cv · (T4-T1)   [J/kg]

Issues a warning if computed efficiency exceeds Carnot limit.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r": {
      "type": "number",
      "description": "Compression ratio v1/v2. Must be > 1."
    },
    "T1": {
      "type": "number",
      "description": "Temperature at state 1 / BDC inlet (K). Must be > 0."
    },
    "T3": {
      "type": "number",
      "description": "Peak temperature at state 3 (after heat addition) (K). Must be > T2."
    },
    "k": {
      "type": "number",
      "description": "Specific heat ratio (default 1.4)."
    },
    "cp": {
      "type": "number",
      "description": "cp (J/kg\u00b7K). Default 1005."
    },
    "cv": {
      "type": "number",
      "description": "cv (J/kg\u00b7K). Default 717.86."
    }
  },
  "required": [
    "r",
    "T1",
    "T3"
  ]
}
```

---

## `thermo_diesel_cycle`

Air-standard Diesel cycle (ideal compression-ignition engine).

    r   = v1/v2  (compression ratio)
    r_c = v3/v2  (cutoff ratio; v3 = volume at end of heat addition)
    η_Diesel = 1 - (r_c^k - 1) / (k · r^(k-1) · (r_c - 1))

Issues a warning if computed efficiency exceeds Carnot limit.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r": {
      "type": "number",
      "description": "Compression ratio v1/v2. Must be > 1."
    },
    "r_c": {
      "type": "number",
      "description": "Cutoff ratio v3/v2. Must be in (1, r)."
    },
    "T1": {
      "type": "number",
      "description": "Temperature at state 1 (K). Must be > 0."
    },
    "k": {
      "type": "number",
      "description": "Specific heat ratio (default 1.4)."
    },
    "cp": {
      "type": "number",
      "description": "cp (J/kg\u00b7K). Default 1005."
    },
    "cv": {
      "type": "number",
      "description": "cv (J/kg\u00b7K). Default 717.86."
    }
  },
  "required": [
    "r",
    "r_c",
    "T1"
  ]
}
```

---

## `thermo_dual_cycle`

Air-standard Dual (mixed) cycle.

Heat is added partly at constant volume (pressure ratio r_p)
and partly at constant pressure (cutoff ratio r_c).
Reduces to Otto when r_c=1; to Diesel when r_p=1.

States: 1 BDC → 2 TDC (isentropic compression) → 3 const-V addition
        → 4 const-P addition → 5 BDC (isentropic expansion).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r": {
      "type": "number",
      "description": "Compression ratio v1/v2. Must be > 1."
    },
    "r_p": {
      "type": "number",
      "description": "Pressure ratio at const-V addition p3/p2. Must be >= 1."
    },
    "r_c": {
      "type": "number",
      "description": "Cutoff ratio v4/v3. Must be >= 1."
    },
    "T1": {
      "type": "number",
      "description": "Temperature at state 1 (K). Must be > 0."
    },
    "k": {
      "type": "number",
      "description": "Specific heat ratio (default 1.4)."
    },
    "cp": {
      "type": "number",
      "description": "cp (J/kg\u00b7K). Default 1005."
    },
    "cv": {
      "type": "number",
      "description": "cv (J/kg\u00b7K). Default 717.86."
    }
  },
  "required": [
    "r",
    "r_p",
    "r_c",
    "T1"
  ]
}
```

---

## `thermo_brayton_cycle`

Air-standard Brayton cycle (gas-turbine cycle).

Supports ideal (eta_c=eta_t=1) or with isentropic component efficiencies,
and optional regeneration (recuperator pre-heats compressed air with
turbine exhaust).

    w_net = w_t - w_c
    η = w_net / q_in
    BWR = w_c / w_t   (back-work ratio; typically 40-80% for gas turbines)

Issues a warning if computed efficiency exceeds Carnot limit.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "r_p": {
      "type": "number",
      "description": "Pressure ratio p2/p1. Must be > 1."
    },
    "T1": {
      "type": "number",
      "description": "Compressor inlet temperature (K). Must be > 0."
    },
    "T3": {
      "type": "number",
      "description": "Turbine inlet temperature (K). Must be > T2."
    },
    "k": {
      "type": "number",
      "description": "Specific heat ratio (default 1.4)."
    },
    "cp": {
      "type": "number",
      "description": "cp (J/kg\u00b7K). Default 1005."
    },
    "eta_c": {
      "type": "number",
      "description": "Isentropic efficiency of compressor (0,1]. Default 1.0."
    },
    "eta_t": {
      "type": "number",
      "description": "Isentropic efficiency of turbine (0,1]. Default 1.0."
    },
    "eta_regen": {
      "type": "number",
      "description": "Regenerator effectiveness [0,1). 0 = no regeneration (default)."
    }
  },
  "required": [
    "r_p",
    "T1",
    "T3"
  ]
}
```

---

## `thermo_rankine_cycle_ideal`

Simplified ideal Rankine (steam) cycle — parametric engineering estimates.

Uses an Antoine-form saturation temperature approximation (valid ~10 kPa–10 MPa).
NOT a substitute for IAPWS-IF97 tables; use for cycle selection and preliminary design.

Supports:
  • Saturated or superheated steam at turbine inlet
  • Pump and turbine isentropic efficiencies
  • Single reheat stage
  • Open feedwater heater count (informational note)

Issues a warning if computed efficiency exceeds Carnot limit.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p_high": {
      "type": "number",
      "description": "Boiler / high-side pressure (Pa). Must be > p_low."
    },
    "p_low": {
      "type": "number",
      "description": "Condenser / low-side pressure (Pa). Must be > 0."
    },
    "T_superheat": {
      "type": "number",
      "description": "Turbine inlet temperature (K) for superheated steam. Omit or set null for saturated vapour at p_high."
    },
    "eta_pump": {
      "type": "number",
      "description": "Isentropic pump efficiency (0,1]. Default 1.0."
    },
    "eta_turbine": {
      "type": "number",
      "description": "Isentropic turbine efficiency (0,1]. Default 1.0."
    },
    "T_reheat": {
      "type": "number",
      "description": "Reheat temperature (K) at p_reheat. Omit = no reheat."
    },
    "p_reheat": {
      "type": "number",
      "description": "Reheat pressure (Pa). Required when T_reheat is given."
    },
    "n_feedwater_heaters": {
      "type": "integer",
      "description": "Number of open feedwater heaters (0-3). Informational only."
    }
  },
  "required": [
    "p_high",
    "p_low"
  ]
}
```

---

## `thermo_refrigeration_cop`

Coefficient of Performance (COP) for a refrigeration or heat-pump cycle.

    COP_R  = Q_L / W_in           (refrigeration)
    COP_HP = (Q_L + W_in) / W_in  (heat pump)
    Q_H = Q_L + W_in

If T_H and T_L are provided, the computed COP is compared against the
reverse-Carnot limit; a warning is issued if COP > COP_Carnot.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q_L": {
      "type": "number",
      "description": "Heat removed from cold space per cycle (J or W). Must be > 0."
    },
    "W_in": {
      "type": "number",
      "description": "Net work input per cycle (J or W). Must be > 0."
    },
    "T_H": {
      "type": "number",
      "description": "High-temperature reservoir (K). Optional; enables Carnot comparison."
    },
    "T_L": {
      "type": "number",
      "description": "Low-temperature reservoir (K). Optional; enables Carnot comparison."
    },
    "mode": {
      "type": "string",
      "enum": [
        "refrigeration",
        "heat_pump"
      ],
      "description": "'refrigeration' (default) or 'heat_pump'."
    }
  },
  "required": [
    "Q_L",
    "W_in"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
