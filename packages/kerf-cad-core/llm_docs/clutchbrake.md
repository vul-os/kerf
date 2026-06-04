# clutchbrake

*Module: `kerf_cad_core.clutchbrake.tools` · Domain: cad*

This module registers **11** LLM tool(s):

- [`disc_clutch_torque`](#disc-clutch-torque)
- [`cone_clutch_torque`](#cone-clutch-torque)
- [`band_brake_torque`](#band-brake-torque)
- [`drum_brake_torque`](#drum-brake-torque)
- [`disc_brake_torque`](#disc-brake-torque)
- [`engagement_energy`](#engagement-energy)
- [`clutch_temperature_rise`](#clutch-temperature-rise)
- [`clutch_heat_dissipation_area`](#clutch-heat-dissipation-area)
- [`clutch_wear_pv_check`](#clutch-wear-pv-check)
- [`engagement_time`](#engagement-time)
- [`friction_material_props`](#friction-material-props)

---

## `disc_clutch_torque`

Compute the torque capacity of a disc / plate clutch.

Supports uniform-wear (Shigley §16-2, preferred for design) and uniform-pressure (new or relapped surfaces) theories. Multi-plate configurations are handled via n_plates.

Returns torque_Nm (total), torque per friction surface, effective friction radius, and actuation force relationship.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "F_a": {
      "type": "number",
      "description": "Axial actuation force (N). Must be > 0."
    },
    "mu": {
      "type": "number",
      "description": "Coefficient of friction (dimensionless). Must be > 0."
    },
    "r_o": {
      "type": "number",
      "description": "Outer friction radius (m). Must be > r_i."
    },
    "r_i": {
      "type": "number",
      "description": "Inner friction radius (m). Must be >= 0."
    },
    "method": {
      "type": "string",
      "enum": [
        "uniform-wear",
        "uniform-pressure"
      ],
      "description": "Pressure distribution theory: 'uniform-wear' (default, conservative) or 'uniform-pressure' (new surfaces)."
    },
    "n_plates": {
      "type": "integer",
      "description": "Number of friction disc pairs (default 1). Each pair contributes 2 friction surfaces."
    }
  },
  "required": [
    "F_a",
    "mu",
    "r_o",
    "r_i"
  ]
}
```

---

## `cone_clutch_torque`

Compute the torque capacity and actuation force of a cone clutch.

The cone half-angle α is from the rotation axis to the cone surface (typically 8°–15°). Below ~6° the clutch may self-lock.

Returns torque_Nm, actuation force, effective friction radius, sin(α), and self_lock flag.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "F_a": {
      "type": "number",
      "description": "Axial engagement force (N). Must be > 0."
    },
    "mu": {
      "type": "number",
      "description": "Coefficient of friction. Must be > 0."
    },
    "r_o": {
      "type": "number",
      "description": "Outer cone radius (m). Must be > r_i."
    },
    "r_i": {
      "type": "number",
      "description": "Inner cone radius (m). Must be >= 0."
    },
    "half_angle_deg": {
      "type": "number",
      "description": "Cone half-angle \u03b1 (degrees). Must be > 0. Typical: 8\u201315\u00b0."
    },
    "method": {
      "type": "string",
      "enum": [
        "uniform-wear",
        "uniform-pressure"
      ],
      "description": "Pressure distribution: 'uniform-wear' (default) or 'uniform-pressure'."
    }
  },
  "required": [
    "F_a",
    "mu",
    "r_o",
    "r_i",
    "half_angle_deg"
  ]
}
```

---

## `band_brake_torque`

Compute band brake braking torque using the capstan equation.

F_tight / F_slack = exp(μ·θ)
T = (F_tight - F_slack) × r

Returns torque_Nm, tight/slack forces, capstan ratio, and self-energizing factor exp(μ·θ).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "drum_radius": {
      "type": "number",
      "description": "Drum radius r (m). Must be > 0."
    },
    "angle_wrap_deg": {
      "type": "number",
      "description": "Band wrap angle \u03b8 (degrees). Must be > 0."
    },
    "mu": {
      "type": "number",
      "description": "Band-drum coefficient of friction. Must be > 0."
    },
    "F_tight": {
      "type": "number",
      "description": "Tight-side band tension (N). Must be > 0."
    },
    "self_energizing": {
      "type": "boolean",
      "description": "If true, report the self-energizing factor exp(\u03bc\u00b7\u03b8). Default false."
    }
  },
  "required": [
    "drum_radius",
    "angle_wrap_deg",
    "mu",
    "F_tight"
  ]
}
```

---

## `drum_brake_torque`

Compute drum brake torque using the Shigley long-shoe formulation.

Handles leading (self-energizing) and trailing (self-dragging) shoes. A self-locking warning is issued when the leading shoe geometry causes M_f >= M_n.

Returns torque_Nm, required actuating force, M_n, M_f, and self_energizing flag.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "drum_radius": {
      "type": "number",
      "description": "Drum radius r (m). Must be > 0."
    },
    "shoe_width": {
      "type": "number",
      "description": "Shoe face width b (m). Must be > 0."
    },
    "mu": {
      "type": "number",
      "description": "Coefficient of friction. Must be > 0."
    },
    "p_max": {
      "type": "number",
      "description": "Maximum contact pressure on shoe (Pa). Must be > 0."
    },
    "theta1_deg": {
      "type": "number",
      "description": "Shoe leading-edge angle from pivot (degrees). Typically 0\u201330\u00b0."
    },
    "theta2_deg": {
      "type": "number",
      "description": "Shoe trailing-edge angle from pivot (degrees). Must be > theta1_deg."
    },
    "pivot_a": {
      "type": "number",
      "description": "Distance from drum centre to shoe pivot (m). Must be > 0."
    },
    "shoe_type": {
      "type": "string",
      "enum": [
        "leading",
        "trailing"
      ],
      "description": "'leading' (default, self-energizing) or 'trailing' (self-dragging)."
    }
  },
  "required": [
    "drum_radius",
    "shoe_width",
    "mu",
    "p_max",
    "theta1_deg",
    "theta2_deg",
    "pivot_a"
  ]
}
```

---

## `disc_brake_torque`

Compute caliper disc brake braking torque.

T = n_pads × μ × F_clamp × r_eff

Returns torque_Nm for the specified number of pads.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "F_clamp": {
      "type": "number",
      "description": "Clamping force per pad (N). Must be > 0."
    },
    "mu": {
      "type": "number",
      "description": "Pad-rotor coefficient of friction. Must be > 0."
    },
    "r_eff": {
      "type": "number",
      "description": "Effective friction radius \u2014 typically mid-pad radius (m). Must be > 0."
    },
    "n_pads": {
      "type": "integer",
      "description": "Number of friction pads (default 2 for floating caliper, 4 for fixed caliper)."
    }
  },
  "required": [
    "F_clamp",
    "mu",
    "r_eff"
  ]
}
```

---

## `engagement_energy`

Compute energy dissipated during a clutch / brake engagement.

Two components:
  1. Kinetic energy from inertia redistribution:  ½·I_eff·Δω²
  2. Work done against load during slip (optional).

Returns E_slip_J (total), E_kinetic_J, E_load_J, Δω, I_eff.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "omega1_rad_s": {
      "type": "number",
      "description": "Driving shaft angular velocity (rad/s). Must be >= 0."
    },
    "omega2_rad_s": {
      "type": "number",
      "description": "Driven shaft initial angular velocity (rad/s). Must be >= 0."
    },
    "I_driving": {
      "type": "number",
      "description": "Driving-side mass moment of inertia (kg\u00b7m\u00b2). Must be > 0."
    },
    "I_driven": {
      "type": "number",
      "description": "Driven-side mass moment of inertia (kg\u00b7m\u00b2). Must be > 0."
    },
    "T_load_Nm": {
      "type": "number",
      "description": "Resisting load torque on driven side (N\u00b7m, default 0)."
    },
    "t_engage_s": {
      "type": "number",
      "description": "Engagement/slip time (s). If provided, load work is added to slip energy. Must be > 0 if given."
    }
  },
  "required": [
    "omega1_rad_s",
    "omega2_rad_s",
    "I_driving",
    "I_driven"
  ]
}
```

---

## `clutch_temperature_rise`

Estimate the lumped temperature rise of the rotor/drum from one clutch or brake engagement.

ΔT = (fraction × E_slip) / (m × cp)

Returns delta_T_K (°C increment). Input E_slip_J from engagement_energy.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "E_slip_J": {
      "type": "number",
      "description": "Slip energy dissipated (J). Must be > 0."
    },
    "mass_rotor_kg": {
      "type": "number",
      "description": "Effective thermal mass of rotor/drum (kg). Must be > 0."
    },
    "cp_J_per_kgK": {
      "type": "number",
      "description": "Specific heat (J/kg\u00b7K). Default 500 (steel/cast iron). Must be > 0."
    },
    "fraction_to_rotor": {
      "type": "number",
      "description": "Fraction of slip energy going to the rotor (0\u20131). Default 0.5."
    }
  },
  "required": [
    "E_slip_J",
    "mass_rotor_kg"
  ]
}
```

---

## `clutch_heat_dissipation_area`

Compute the minimum heat-dissipation area for steady-state convective cooling of a clutch or brake.

A = Q / (h × ΔT)

Returns area_m2 (m²).

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "power_W": {
      "type": "number",
      "description": "Heat dissipation power (W). Must be > 0."
    },
    "h_conv": {
      "type": "number",
      "description": "Convective heat-transfer coefficient (W/m\u00b2\u00b7K). Default 20 (natural convection in air). Must be > 0."
    },
    "delta_T_K": {
      "type": "number",
      "description": "Allowable surface-to-ambient temperature difference (K). Default 80 K. Must be > 0."
    }
  },
  "required": [
    "power_W"
  ]
}
```

---

## `clutch_wear_pv_check`

Check whether the contact pressure × slip velocity (pV) product is within the friction material's allowable limit.

Returns pv_Pa_m_s, pv_max, pv_ok, safety_factor, and warnings if the limit is exceeded.

Available materials include: cast_iron_dry, cast_iron_wet, molded_dry, molded_wet, sintered_metal_dry, paper_wet, carbon_graphite, asbestos_dry, asbestos_wet, bronze_dry, steel_dry, cork_dry, wood_dry.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "p_contact": {
      "type": "number",
      "description": "Average contact pressure on friction surface (Pa). Must be > 0."
    },
    "v_slip": {
      "type": "number",
      "description": "Average sliding / slip velocity at friction surface (m/s). Must be > 0."
    },
    "material": {
      "type": "string",
      "description": "Friction material name from built-in catalog (e.g. 'cast_iron_dry', 'molded_dry', 'sintered_metal_dry')."
    }
  },
  "required": [
    "p_contact",
    "v_slip",
    "material"
  ]
}
```

---

## `engagement_time`

Compute the synchronisation time and slip energy during a clutch engagement assuming constant transmitted torque.

t_sync = Δω × I₁ × I₂ / [(T_c - T_load) × (I₁ + I₂)]

Returns t_sync_s, E_slip_J, omega_sync, t_sync_feasible.

Errors: {ok:false, reason} for invalid inputs. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "omega1_rad_s": {
      "type": "number",
      "description": "Driving shaft initial angular velocity (rad/s). Must be >= 0."
    },
    "omega2_rad_s": {
      "type": "number",
      "description": "Driven shaft initial angular velocity (rad/s). Must be >= 0."
    },
    "I_driving": {
      "type": "number",
      "description": "Driving-side inertia (kg\u00b7m\u00b2). Must be > 0."
    },
    "I_driven": {
      "type": "number",
      "description": "Driven-side inertia (kg\u00b7m\u00b2). Must be > 0."
    },
    "T_clutch_Nm": {
      "type": "number",
      "description": "Clutch (transmitted) torque during slip (N\u00b7m). Must be > 0."
    },
    "T_load_Nm": {
      "type": "number",
      "description": "Load torque on driven side (N\u00b7m, default 0)."
    }
  },
  "required": [
    "omega1_rad_s",
    "omega2_rad_s",
    "I_driving",
    "I_driven",
    "T_clutch_Nm"
  ]
}
```

---

## `friction_material_props`

Look up friction material properties from the built-in catalog.

Returns μ (dry coefficient of friction), max_pV (Pa·m/s), and max_temp (°C) for the specified material.

Available materials: cast_iron_dry, cast_iron_wet, steel_dry, bronze_dry, asbestos_dry, asbestos_wet, molded_dry, molded_wet, paper_wet, sintered_metal_dry, cork_dry, wood_dry, carbon_graphite.

Errors: {ok:false, reason} for unknown material. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "material": {
      "type": "string",
      "description": "Friction material name from the built-in catalog (e.g. 'cast_iron_dry', 'molded_dry', 'sintered_metal_dry')."
    }
  },
  "required": [
    "material"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
