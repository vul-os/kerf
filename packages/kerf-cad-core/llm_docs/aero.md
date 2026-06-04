# aero

*Module: `kerf_cad_core.aero.tools` · Domain: cad*

This module registers **10** LLM tool(s):

- [`aero_atmosphere`](#aero-atmosphere)
- [`aero_dynamic_pressure`](#aero-dynamic-pressure)
- [`aero_mach`](#aero-mach)
- [`aero_thin_airfoil`](#aero-thin-airfoil)
- [`aero_finite_wing`](#aero-finite-wing)
- [`aero_drag_buildup`](#aero-drag-buildup)
- [`aero_level_flight`](#aero-level-flight)
- [`aero_climb_rate`](#aero-climb-rate)
- [`aero_propeller`](#aero-propeller)
- [`aero_breguet`](#aero-breguet)

---

## `aero_atmosphere`

Compute ICAO Standard Atmosphere properties at a given altitude.

Returns temperature T (K), pressure p (Pa), air density ρ (kg/m³), and speed of sound a (m/s).

Covers troposphere (0–11 000 m, lapse rate −6.5 K/km) and isothermal stratosphere (11 000–20 000 m, T = 216.65 K).

Errors: {ok:false, reason} for out-of-range or invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "altitude_m": {
      "type": "number",
      "description": "Geopotential altitude (m).  Range: 0 \u2013 20 000 m."
    }
  },
  "required": [
    "altitude_m"
  ]
}
```

---

## `aero_dynamic_pressure`

Compute dynamic pressure q = ½ ρ V²  (Pa).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "rho": {
      "type": "number",
      "description": "Air density (kg/m\u00b3). Must be > 0."
    },
    "V": {
      "type": "number",
      "description": "Airspeed (m/s). Must be >= 0."
    }
  },
  "required": [
    "rho",
    "V"
  ]
}
```

---

## `aero_mach`

Compute Mach number M = V / a and Prandtl-Glauert compressibility correction factor β = √(1 − M²).

Issues a transonic flag when M > 0.7 (PG correction degrades).

Tip: use aero_atmosphere to get the local speed of sound 'a' at altitude.

Errors: {ok:false, reason} for M >= 1 or invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "V": {
      "type": "number",
      "description": "Airspeed (m/s). Must be >= 0."
    },
    "a": {
      "type": "number",
      "description": "Speed of sound (m/s). Must be > 0. Use aero_atmosphere to get local a."
    }
  },
  "required": [
    "V",
    "a"
  ]
}
```

---

## `aero_thin_airfoil`

Thin-airfoil theory: section lift coefficient and quarter-chord pitching moment coefficient.

  Cl      = 2π (α − α₀)          [dCl/dα = 2π rad⁻¹]
  Cm_c/4  = −(π/2)(α − α₀)       [about aerodynamic centre]

A stall warning is issued when |Cl| > 1.4.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha_deg": {
      "type": "number",
      "description": "Angle of attack (degrees).  Converted to radians internally."
    },
    "alpha0_deg": {
      "type": "number",
      "description": "Zero-lift angle of attack (degrees).  0 for symmetric airfoils; typically negative for cambered.  Default 0."
    }
  },
  "required": [
    "alpha_deg"
  ]
}
```

---

## `aero_finite_wing`

Prandtl lifting-line finite-wing analysis.

Computes:
  a_wing  — finite-wing lift-curve slope (rad⁻¹)
              a = a₀ / (1 + a₀/(π AR e))
  CL      — wing lift coefficient
  CDi     — induced drag coefficient  CL²/(π AR e)

A stall warning is issued when |CL| > 1.6.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "alpha_deg": {
      "type": "number",
      "description": "Angle of attack (degrees)."
    },
    "alpha0_deg": {
      "type": "number",
      "description": "Zero-lift angle of attack (degrees).  Default 0."
    },
    "AR": {
      "type": "number",
      "description": "Wing aspect ratio b\u00b2/S.  Must be > 0."
    },
    "e": {
      "type": "number",
      "description": "Oswald span efficiency factor (0 < e \u2264 1).  Typical values: 0.75\u20130.95.  Default 0.85."
    },
    "a0": {
      "type": "number",
      "description": "Section lift-curve slope (rad\u207b\u00b9).  Default 2\u03c0 \u2248 6.283 (thin-airfoil theory)."
    }
  },
  "required": [
    "alpha_deg",
    "AR"
  ]
}
```

---

## `aero_drag_buildup`

Total drag buildup: parasite + induced; L/D; best-glide condition.

  CD      = CD0 + CL² / (π AR e)
  L/D     = CL / CD
  CL_best = √(π AR e CD0)   (CL for maximum L/D)
  (L/D)_max = CL_best / (2 CD0)

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "CD0": {
      "type": "number",
      "description": "Zero-lift (parasite) drag coefficient.  Must be >= 0."
    },
    "CL": {
      "type": "number",
      "description": "Lift coefficient at the flight condition."
    },
    "AR": {
      "type": "number",
      "description": "Wing aspect ratio.  Must be > 0."
    },
    "e": {
      "type": "number",
      "description": "Oswald span efficiency factor (0 < e \u2264 1).  Default 0.85."
    }
  },
  "required": [
    "CD0",
    "CL",
    "AR"
  ]
}
```

---

## `aero_level_flight`

Level-flight performance: required thrust, shaft power, and stall speed.

  T_req   = W × CD/CL           (N)
  P_req   = T_req × V            (W)
  V_stall = √(2W / (ρ S CLmax)) (m/s)

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "W": {
      "type": "number",
      "description": "Aircraft weight (N).  Must be > 0."
    },
    "CL": {
      "type": "number",
      "description": "Lift coefficient at flight condition.  Must be > 0."
    },
    "CD": {
      "type": "number",
      "description": "Drag coefficient at flight condition.  Must be > 0."
    },
    "V": {
      "type": "number",
      "description": "True airspeed (m/s).  Must be > 0."
    },
    "rho": {
      "type": "number",
      "description": "Air density (kg/m\u00b3).  Required for stall speed.  Must be > 0."
    },
    "S": {
      "type": "number",
      "description": "Wing reference area (m\u00b2).  Required for stall speed.  Must be > 0."
    },
    "CLmax": {
      "type": "number",
      "description": "Maximum lift coefficient.  Required for stall speed.  Must be > 0."
    }
  },
  "required": [
    "W",
    "CL",
    "CD",
    "V"
  ]
}
```

---

## `aero_climb_rate`

Rate of climb from excess-power method.

  RC = (T − D) × V / W   (m/s)

A negative-climb warning is issued when T ≤ D.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "T": {
      "type": "number",
      "description": "Available thrust (N).  Must be >= 0."
    },
    "D": {
      "type": "number",
      "description": "Drag at climb airspeed (N).  Must be >= 0."
    },
    "V": {
      "type": "number",
      "description": "True airspeed (m/s).  Must be > 0."
    },
    "W": {
      "type": "number",
      "description": "Aircraft weight (N).  Must be > 0."
    }
  },
  "required": [
    "T",
    "D",
    "V",
    "W"
  ]
}
```

---

## `aero_propeller`

Ideal propeller (actuator-disc) thrust and efficiency.

Actuator-disc (Froude momentum theory):
  T      = 2 ρ A (V_inf + w) w   (N)
  P_in   = T × (V_inf + w)        (W)
  η      = V_inf / (V_inf + w)    (dimensionless)

Disc area: A = π r² for propeller radius r.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "rho": {
      "type": "number",
      "description": "Air density (kg/m\u00b3).  Must be > 0."
    },
    "A_disc": {
      "type": "number",
      "description": "Propeller disc area (m\u00b2) = \u03c0 r\u00b2.  Must be > 0."
    },
    "V_inf": {
      "type": "number",
      "description": "Freestream velocity (m/s).  Must be >= 0."
    },
    "w": {
      "type": "number",
      "description": "Induced velocity at disc (m/s).  Must be > 0."
    }
  },
  "required": [
    "rho",
    "A_disc",
    "V_inf",
    "w"
  ]
}
```

---

## `aero_breguet`

Breguet range and endurance equations for propeller-driven aircraft.

Range:     R = (η_p / c) × (L/D) × ln(W_i / W_f)          (m)
Endurance: E = (η_p / c) × (CL/CD) × (1/g) × ln(W_i / W_f) (s)

c_specific — specific fuel consumption (kg/(N·s)).
  Typical piston: ~8e-8 kg/(N·s); turboprop: ~5e-8 kg/(N·s).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "eta_p": {
      "type": "number",
      "description": "Propeller efficiency (0 < \u03b7_p \u2264 1)."
    },
    "c_specific": {
      "type": "number",
      "description": "Specific fuel consumption (kg/(N\u00b7s)).  Must be > 0."
    },
    "CL": {
      "type": "number",
      "description": "Lift coefficient at cruise.  Must be > 0."
    },
    "CD": {
      "type": "number",
      "description": "Drag coefficient at cruise.  Must be > 0."
    },
    "W_initial": {
      "type": "number",
      "description": "Take-off weight (N).  Must be > W_final."
    },
    "W_final": {
      "type": "number",
      "description": "Landing weight (N).  Must be > 0."
    }
  },
  "required": [
    "eta_p",
    "c_specific",
    "CL",
    "CD",
    "W_initial",
    "W_final"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
