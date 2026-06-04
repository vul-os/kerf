# shaft

*Module: `kerf_cad_core.shaft.tools` · Domain: cad*

This module registers **4** LLM tool(s):

- [`shaft_diameter`](#shaft-diameter)
- [`shaft_critical_speed`](#shaft-critical-speed)
- [`bearing_l10`](#bearing-l10)
- [`key_size`](#key-size)

---

## `shaft_diameter`

Compute the required minimum solid circular shaft diameter from combined bending and torsion loads.

Two methods are supported:
  'DE-Goodman' (default) — Distortion-Energy / Goodman criterion per ASME B106; uses Von Mises equivalent stress; suitable for fatigue-loaded rotating shafts.  sigma_allow should be the endurance limit Se (Pa).
  'max-shear'            — Tresca / maximum-shear-stress criterion; suitable for static or shock-loaded shafts.

Returns diameter_m (metres).  Both M and T may be zero (returns 0.0).

Errors: {ok:false, reason} for invalid / negative inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "M": {
      "type": "number",
      "description": "Bending moment (N\u00b7m). Must be >= 0."
    },
    "T": {
      "type": "number",
      "description": "Torsional moment / torque (N\u00b7m). Must be >= 0."
    },
    "sigma_allow": {
      "type": "number",
      "description": "Allowable normal stress (Pa). For DE-Goodman: endurance limit Se. For max-shear: allowable bending stress. Must be > 0."
    },
    "method": {
      "type": "string",
      "enum": [
        "DE-Goodman",
        "max-shear"
      ],
      "description": "Sizing criterion: 'DE-Goodman' (default) or 'max-shear'."
    },
    "Kf": {
      "type": "number",
      "description": "Fatigue stress concentration factor for bending (default 1.0)."
    },
    "Kfs": {
      "type": "number",
      "description": "Fatigue stress concentration factor for torsion (default 1.0)."
    },
    "safety_factor": {
      "type": "number",
      "description": "Additional safety factor on the required diameter (default 1.0)."
    }
  },
  "required": [
    "M",
    "T",
    "sigma_allow"
  ]
}
```

---

## `shaft_critical_speed`

Compute the first lateral (whirl) critical speed of a uniform shaft.

Uses the Euler-Bernoulli beam equation.  The boundary condition ('simply-supported' or 'fixed-fixed') determines the first eigenvalue β₁·L used in the formula.

Returns omega_rad_s (rad/s) and n_rpm.
Operating speed should remain ≤ 75% of n_rpm to avoid resonance.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "length_m": {
      "type": "number",
      "description": "Shaft length (m). Must be > 0."
    },
    "mass_per_m": {
      "type": "number",
      "description": "Mass per unit length (kg/m). Must be > 0. For solid steel: mass_per_m \u2248 7850 \u00d7 \u03c0/4 \u00d7 d\u00b2."
    },
    "E": {
      "type": "number",
      "description": "Young's modulus (Pa). Must be > 0. Steel \u2248 200e9 Pa."
    },
    "I": {
      "type": "number",
      "description": "Second moment of area (m\u2074). Must be > 0. Solid circle: \u03c0\u00b7d\u2074/64."
    },
    "supports": {
      "type": "string",
      "enum": [
        "simply-supported",
        "fixed-fixed"
      ],
      "description": "Boundary condition: 'simply-supported' (default) or 'fixed-fixed'."
    }
  },
  "required": [
    "length_m",
    "mass_per_m",
    "E",
    "I"
  ]
}
```

---

## `bearing_l10`

Compute the ISO 281 basic rating life L10 for a rolling bearing.

L10 is the life that 90% of a group of identical bearings will achieve or exceed under identical operating conditions.

  ball bearings:   p = 3     → L10 = (C/P)³      [10⁶ rev]
  roller bearings: p = 10/3  → L10 = (C/P)^(10/3) [10⁶ rev]

Returns L10_rev (10⁶ revolutions) and L10_hours at the given speed.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "C": {
      "type": "number",
      "description": "Basic dynamic load rating (N). From bearing manufacturer data. Must be > 0."
    },
    "P": {
      "type": "number",
      "description": "Equivalent dynamic bearing load (N). P = X\u00b7Fr + Y\u00b7Fa per ISO 281. Must be > 0."
    },
    "n_rpm": {
      "type": "number",
      "description": "Rotational speed (rpm). Must be > 0."
    },
    "bearing_type": {
      "type": "string",
      "enum": [
        "ball",
        "roller"
      ],
      "description": "Bearing type: 'ball' (p=3, default) or 'roller' (p=10/3)."
    }
  },
  "required": [
    "C",
    "P",
    "n_rpm"
  ]
}
```

---

## `key_size`

Select the standard key cross-section per ANSI B17.1 / DIN 6885 for a given shaft diameter, and verify shear and bearing stresses.

The key cross-section (width × height) is looked up from the standard table for the shaft diameter (range 6–230 mm).  Then shear stress (τ = F / (w·L)) and bearing/compressive stress (σ_c = F / (h/2·L)) are computed from the transmitted torque.

Returns key dimensions, computed stresses, allowables, pass/fail flags, and safety factors.

Errors: {ok:false, reason} for out-of-range shaft diameter or invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "shaft_d_mm": {
      "type": "number",
      "description": "Shaft diameter (mm). Valid range: 6\u2013230 mm."
    },
    "torque_Nm": {
      "type": "number",
      "description": "Transmitted torque (N\u00b7m). Must be >= 0."
    },
    "material": {
      "type": "string",
      "enum": [
        "steel_1045",
        "steel_1020",
        "stainless_304",
        "cast_iron"
      ],
      "description": "Key material (default 'steel_1045'): steel_1045 \u03c4=170 MPa \u03c3_c=340 MPa, steel_1020 \u03c4=120 MPa \u03c3_c=240 MPa, stainless_304 \u03c4=115 MPa \u03c3_c=230 MPa, cast_iron \u03c4=55 MPa \u03c3_c=110 MPa."
    },
    "key_length_mm": {
      "type": "number",
      "description": "Key length (mm). If omitted, defaults to 1.5 \u00d7 shaft_d_mm."
    }
  },
  "required": [
    "shaft_d_mm",
    "torque_Nm"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
