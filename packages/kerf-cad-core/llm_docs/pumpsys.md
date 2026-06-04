# pumpsys

*Module: `kerf_cad_core.pumpsys.tools` · Domain: cad*

This module registers **13** LLM tool(s):

- [`pump_system_curve`](#pump-system-curve)
- [`pump_system_K_from_pipe`](#pump-system-K-from-pipe)
- [`pump_curve_fit`](#pump-curve-fit)
- [`pump_operating_point`](#pump-operating-point)
- [`pump_hydraulic_power`](#pump-hydraulic-power)
- [`pump_npsh_available`](#pump-npsh-available)
- [`pump_npsh_check`](#pump-npsh-check)
- [`pump_affinity_speed`](#pump-affinity-speed)
- [`pump_affinity_trim`](#pump-affinity-trim)
- [`pumps_in_series`](#pumps-in-series)
- [`pumps_in_parallel`](#pumps-in-parallel)
- [`pump_specific_speed`](#pump-specific-speed)
- [`pump_minimum_flow_check`](#pump-minimum-flow-check)

---

## `pump_system_curve`

Compute the system head at a given flow rate using the model H_sys = H_static + K·Q².

K lumps all pipe-friction (Darcy-Weisbach) and minor-fitting losses.
Use pump_system_K_from_pipe to compute K from pipe geometry.

Returns H_system_m (metres). Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "H_static": {
      "type": "number",
      "description": "Static head (m). Must be >= 0."
    },
    "K": {
      "type": "number",
      "description": "System resistance coefficient (s\u00b2/m\u2075). Must be >= 0."
    },
    "Q": {
      "type": "number",
      "description": "Volume flow rate (m\u00b3/s). Must be >= 0."
    }
  },
  "required": [
    "H_static",
    "K",
    "Q"
  ]
}
```

---

## `pump_system_K_from_pipe`

Compute the system resistance coefficient K from Darcy-Weisbach pipe friction and minor fittings.

K = (f·L/D + K_fittings) / (2·g·A²)

Returns K (s²/m⁵). Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "f": {
      "type": "number",
      "description": "Darcy friction factor (dimensionless). Must be > 0."
    },
    "L": {
      "type": "number",
      "description": "Pipe length (m). Must be > 0."
    },
    "D": {
      "type": "number",
      "description": "Internal pipe diameter (m). Must be > 0."
    },
    "A": {
      "type": "number",
      "description": "Pipe cross-sectional area (m\u00b2). Must be > 0. Circular pipe: A = \u03c0\u00b7D\u00b2/4."
    },
    "K_fittings": {
      "type": "number",
      "description": "Sum of minor-loss coefficients for fittings (dimensionless). Default 0."
    }
  },
  "required": [
    "f",
    "L",
    "D",
    "A"
  ]
}
```

---

## `pump_curve_fit`

Fit a quadratic pump curve H = a·Q² + b·Q + c from ≥ 3 catalogue (Q, H) points (Q in m³/s, H in m).

For exactly 3 points the quadratic passes through all three. For > 3 points, a least-squares fit is used.

Returns coefficients a, b, c, H_shutoff (head at Q=0), and Q_max.
Use with pump_operating_point to find the duty point. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "points": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "description": "List of [Q, H] pairs (m\u00b3/s, m) from the pump datasheet. At least 3 distinct Q values required.",
      "minItems": 3
    }
  },
  "required": [
    "points"
  ]
}
```

---

## `pump_operating_point`

Find the pump operating point (duty point): intersection of the pump curve H = a·Q² + b·Q + c and the system curve H = H_static + K·Q².

Solves the quadratic (a−K)·Q² + b·Q + (c−H_static) = 0.

Returns Q_op_m3s (m³/s) and H_op_m (m). Flags negative-flow or no-real-intersection. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "a": {
      "type": "number",
      "description": "Pump curve coefficient a (H = a\u00b7Q\u00b2 + b\u00b7Q + c)."
    },
    "b": {
      "type": "number",
      "description": "Pump curve coefficient b."
    },
    "c": {
      "type": "number",
      "description": "Pump curve coefficient c (shut-off head)."
    },
    "H_static": {
      "type": "number",
      "description": "Static system head (m). Must be >= 0."
    },
    "K": {
      "type": "number",
      "description": "System resistance coefficient (s\u00b2/m\u2075). Must be >= 0."
    }
  },
  "required": [
    "a",
    "b",
    "c",
    "H_static",
    "K"
  ]
}
```

---

## `pump_hydraulic_power`

Compute hydraulic (fluid) power, brake (shaft) power, and efficiency.

P_hydraulic = ρ·g·Q·H
P_brake     = P_hydraulic / η
η           = P_hydraulic / P_brake

Provide either eta OR P_shaft_W; the other is computed. If neither is given, only P_hydraulic is returned. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q": {
      "type": "number",
      "description": "Volume flow rate (m\u00b3/s). Must be > 0."
    },
    "H": {
      "type": "number",
      "description": "Total dynamic head (m). Must be > 0."
    },
    "rho": {
      "type": "number",
      "description": "Fluid density (kg/m\u00b3). Must be > 0. Water \u2248 1000."
    },
    "eta": {
      "type": "number",
      "description": "Overall pump efficiency (0 < \u03b7 \u2264 1). Optional."
    },
    "P_shaft_W": {
      "type": "number",
      "description": "Shaft (brake) power (W). Optional. Mutually exclusive with eta."
    }
  },
  "required": [
    "Q",
    "H",
    "rho"
  ]
}
```

---

## `pump_npsh_available`

Compute Net Positive Suction Head Available (NPSHa).

NPSHa = (P_atm − P_vapor) / (ρ·g) − z_suction − h_friction

z_suction is positive for suction lift (pump above liquid), negative for flooded suction (pump below liquid). Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "P_atm_Pa": {
      "type": "number",
      "description": "Absolute pressure at suction source (Pa). Standard atmosphere \u2248 101325 Pa. Must be > 0."
    },
    "P_vapor_Pa": {
      "type": "number",
      "description": "Vapour pressure of fluid at operating temperature (Pa). Water 20\u00b0C \u2248 2338 Pa. Must be >= 0."
    },
    "rho": {
      "type": "number",
      "description": "Fluid density (kg/m\u00b3). Must be > 0."
    },
    "z_suction_m": {
      "type": "number",
      "description": "Suction lift (m). Positive = pump above liquid (suction lift). Negative = pump below liquid (flooded suction)."
    },
    "h_friction_m": {
      "type": "number",
      "description": "Friction head loss in suction line (m). Must be >= 0."
    }
  },
  "required": [
    "P_atm_Pa",
    "P_vapor_Pa",
    "rho",
    "z_suction_m",
    "h_friction_m"
  ]
}
```

---

## `pump_npsh_check`

Check NPSHa against NPSHr with a cavitation safety margin.

Cavitation risk is flagged when NPSHa < NPSHr + margin_m.
Default margin = 0.5 m per HI standard.

Returns cavitation_risk (bool) and NPSHa − NPSHr difference. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "NPSHa_m": {
      "type": "number",
      "description": "NPSH available (m), from pump_npsh_available."
    },
    "NPSHr_m": {
      "type": "number",
      "description": "NPSH required by the pump (m), from manufacturer data. Must be > 0."
    },
    "margin_m": {
      "type": "number",
      "description": "Cavitation safety margin (m). Default 0.5 m. Must be >= 0."
    }
  },
  "required": [
    "NPSHa_m",
    "NPSHr_m"
  ]
}
```

---

## `pump_affinity_speed`

Apply pump affinity laws for a rotational speed change.

  Q₂ = Q₁·(n₂/n₁)
  H₂ = H₁·(n₂/n₁)²
  P₂ = P₁·(n₂/n₁)³

Valid range: speed ratio 0.5–2.0. Warns outside this range. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q1": {
      "type": "number",
      "description": "Original flow (m\u00b3/s). Must be > 0."
    },
    "H1": {
      "type": "number",
      "description": "Original head (m). Must be > 0."
    },
    "P1": {
      "type": "number",
      "description": "Original power (W). Must be > 0."
    },
    "n1": {
      "type": "number",
      "description": "Original speed (rpm). Must be > 0."
    },
    "n2": {
      "type": "number",
      "description": "New speed (rpm). Must be > 0."
    }
  },
  "required": [
    "Q1",
    "H1",
    "P1",
    "n1",
    "n2"
  ]
}
```

---

## `pump_affinity_trim`

Apply pump affinity laws for an impeller-trim (diameter) change.

  Q₂ = Q₁·(D₂/D₁)
  H₂ = H₁·(D₂/D₁)²
  P₂ = P₁·(D₂/D₁)³

Warns if trim ratio < 70% (accuracy degrades) or > 100% (non-physical). Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q1": {
      "type": "number",
      "description": "Original flow (m\u00b3/s). Must be > 0."
    },
    "H1": {
      "type": "number",
      "description": "Original head (m). Must be > 0."
    },
    "P1": {
      "type": "number",
      "description": "Original power (W). Must be > 0."
    },
    "D1": {
      "type": "number",
      "description": "Original impeller diameter (m). Must be > 0."
    },
    "D2": {
      "type": "number",
      "description": "Trimmed impeller diameter (m). Must be > 0."
    }
  },
  "required": [
    "Q1",
    "H1",
    "P1",
    "D1",
    "D2"
  ]
}
```

---

## `pumps_in_series`

Compute combined head of pumps in series at a given flow rate.

H_combined(Q) = Σ H_i(Q)  where H_i(Q) = a_i·Q² + b_i·Q + c_i

Supply a list of [a, b, c] pump-curve coefficient triples. Returns combined and individual heads at Q_eval. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "curves": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "List of [a, b, c] coefficient triples from pump_curve_fit.",
      "minItems": 1
    },
    "Q_eval": {
      "type": "number",
      "description": "Flow rate at which to evaluate combined head (m\u00b3/s). Must be >= 0."
    }
  },
  "required": [
    "curves",
    "Q_eval"
  ]
}
```

---

## `pumps_in_parallel`

Compute combined flow of pumps in parallel at a given head.

Each pump operates at the common head H_eval; combined flow = Σ Q_i(H).
For each pump, solves a·Q² + b·Q + (c − H) = 0 for the positive root.

Supply a list of [a, b, c] pump-curve coefficient triples. Returns combined and individual flows at H_eval. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "curves": {
      "type": "array",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 3,
        "maxItems": 3
      },
      "description": "List of [a, b, c] coefficient triples from pump_curve_fit.",
      "minItems": 1
    },
    "H_eval": {
      "type": "number",
      "description": "Common head at which to evaluate individual flows (m). Must be >= 0."
    }
  },
  "required": [
    "curves",
    "H_eval"
  ]
}
```

---

## `pump_specific_speed`

Compute true dimensionless specific speed Ns* and recommend impeller type.

Ns* = ω·√Q / (g·H)^(3/4)   (White Fluid Mech. 8th ed. Eq. 11.30b;
  ω in rad/s, g = 9.81 m/s² — genuinely unit-free)

Impeller guidance (White Fig. 11.20 dimensionless bands):
  Ns* < 0.20  — radial (low-Ns); consider PD pump
  0.20–0.75   — radial centrifugal (best efficiency range)
  0.75–1.5    — mixed-flow (Francis)
  Ns* > 1.5   — axial-flow / propeller

Returns Ns (dimensionless), Ns_dimensional, Nss_us_customary,
impeller_type, and guidance text. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q": {
      "type": "number",
      "description": "BEP flow rate (m\u00b3/s). Must be > 0."
    },
    "H": {
      "type": "number",
      "description": "BEP head (m). Must be > 0."
    },
    "n": {
      "type": "number",
      "description": "Rotational speed (rpm). Must be > 0."
    }
  },
  "required": [
    "Q",
    "H",
    "n"
  ]
}
```

---

## `pump_minimum_flow_check`

Check whether the operating flow is above the minimum continuous stable flow (MCSF).

MCSF ≈ 25% of BEP flow (Kaplan §2.4, HI 9.6.4). Below MCSF, risk of recirculation, vibration, and reduced bearing life.

Also warns if Q_op > 120% of BEP (overloading / cavitation risk).

Returns below_min_flow (bool) and Q_fraction. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Q_op": {
      "type": "number",
      "description": "Operating flow rate (m\u00b3/s). Must be >= 0."
    },
    "Q_bep": {
      "type": "number",
      "description": "Best efficiency point (BEP) flow rate (m\u00b3/s). Must be > 0."
    },
    "min_fraction": {
      "type": "number",
      "description": "Minimum-flow fraction of Q_bep (default 0.25 = 25%). Must be in (0, 1)."
    }
  },
  "required": [
    "Q_op",
    "Q_bep"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
