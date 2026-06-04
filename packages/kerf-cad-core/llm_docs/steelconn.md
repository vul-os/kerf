# steelconn

*Module: `kerf_cad_core.steelconn.tools` · Domain: cad*

This module registers **10** LLM tool(s):

- [`electrode_strength`](#electrode-strength)
- [`bolt_shear_capacity`](#bolt-shear-capacity)
- [`bolt_bearing_capacity`](#bolt-bearing-capacity)
- [`bolt_tension_capacity`](#bolt-tension-capacity)
- [`slip_critical_capacity`](#slip-critical-capacity)
- [`block_shear_capacity`](#block-shear-capacity)
- [`bolt_group_eccentric`](#bolt-group-eccentric)
- [`fillet_weld_capacity`](#fillet-weld-capacity)
- [`weld_group_elastic_vector`](#weld-group-elastic-vector)
- [`base_plate_bearing`](#base-plate-bearing)

---

## `electrode_strength`

Return tabulated Fexx (electrode classification strength) for a standard SMAW/FCAW electrode designation.

Supported: E60, E70, E80, E90, E100, E110.

Returns Fexx_Pa and Fexx_ksi.
Errors: {ok:false, reason} for unknown designation.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "designation": {
      "type": "string",
      "enum": [
        "E60",
        "E70",
        "E80",
        "E90",
        "E100",
        "E110"
      ],
      "description": "Electrode designation per AWS A5.1/A5.20."
    }
  },
  "required": [
    "designation"
  ]
}
```

---

## `bolt_shear_capacity`

Compute nominal bolt shear strength per AISC 360-22 J3.6.

Rn = Fnv × Ab × n_bolts × shear_planes

Supports LRFD (φ=0.75) and ASD (Ω=2.00).  Returns Rn, design capacity, utilization ratio, and governing limit state.

Common Fnv values (MPa):
  A325N (threads in plane): 372 MPa
  A325X (threads excluded): 462 MPa
  A490N: 457 MPa,  A490X: 572 MPa

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Ab": {
      "type": "number",
      "description": "Gross bolt cross-sectional area (mm\u00b2). Must be > 0."
    },
    "Fnv": {
      "type": "number",
      "description": "Nominal shear stress of bolt (Pa). See AISC Table J3.2."
    },
    "n_bolts": {
      "type": "integer",
      "description": "Number of bolts. Must be >= 1."
    },
    "shear_planes": {
      "type": "integer",
      "enum": [
        1,
        2
      ],
      "description": "Shear planes: 1 (single shear) or 2 (double shear). Default 1."
    },
    "Vu": {
      "type": "number",
      "description": "Applied shear force (N). Used to compute utilization ratio."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "Design method: 'LRFD' (default, \u03c6=0.75) or 'ASD' (\u03a9=2.00)."
    }
  },
  "required": [
    "Ab",
    "Fnv",
    "n_bolts"
  ]
}
```

---

## `bolt_bearing_capacity`

Compute bolt bearing strength on connected material (AISC 360-22 J3.10).

Deformation-controlled: Rn = 2.4 × d × t × Fu × n_bolts
Clear-distance check:   Rn = 1.2 × lc × t × Fu × n_bolts  (if lc given)
Governing (lesser) value is reported.

Supports LRFD (φ=0.75) and ASD (Ω=2.00).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Fu": {
      "type": "number",
      "description": "Ultimate tensile stress of connected material (Pa)."
    },
    "t": {
      "type": "number",
      "description": "Thickness of connected material (mm). Must be > 0."
    },
    "d": {
      "type": "number",
      "description": "Nominal bolt diameter (mm). Must be > 0."
    },
    "n_bolts": {
      "type": "integer",
      "description": "Number of bolts. Must be >= 1."
    },
    "lc": {
      "type": "number",
      "description": "Clear distance in direction of force (mm). If provided, the 1.2lc\u00b7t\u00b7Fu check is also evaluated."
    },
    "Vu": {
      "type": "number",
      "description": "Applied shear force (N). Used for utilization."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "'LRFD' (default) or 'ASD'."
    }
  },
  "required": [
    "Fu",
    "t",
    "d",
    "n_bolts"
  ]
}
```

---

## `bolt_tension_capacity`

Compute nominal bolt tension strength (AISC 360-22 J3.6).

Rn = Fnt × Ab × n_bolts

Common Fnt values (MPa): A307=310, A325=621, A490=780.
Supports LRFD (φ=0.75) and ASD (Ω=2.00).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Ab": {
      "type": "number",
      "description": "Gross bolt area (mm\u00b2). Must be > 0."
    },
    "Fnt": {
      "type": "number",
      "description": "Nominal tensile stress of bolt (Pa). See AISC Table J3.2."
    },
    "n_bolts": {
      "type": "integer",
      "description": "Number of bolts in tension. Must be >= 1."
    },
    "Tu": {
      "type": "number",
      "description": "Applied tensile force (N). Used for utilization."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "'LRFD' (default) or 'ASD'."
    }
  },
  "required": [
    "Ab",
    "Fnt",
    "n_bolts"
  ]
}
```

---

## `slip_critical_capacity`

Compute slip-critical connection capacity (AISC 360-22 J3.8).

Rn = μ × 1.13 × hf × Pt × n_faying × n_bolts

μ = 0.35 (Class A: unpainted clean mill scale) or 0.50 (Class B).
hf = 1.0 (STD holes), 0.85 (oversized), 0.70 (short-slotted ⊥).
Supports LRFD (φ=1.00) and ASD (Ω=1.50).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "mu": {
      "type": "number",
      "description": "Mean slip coefficient: 0.35 (Class A) or 0.50 (Class B). Must be in (0, 1]."
    },
    "Pt": {
      "type": "number",
      "description": "Minimum fastener tension (N). AISC Table J3.1: 3/4\" A325=133400N, 7/8\" A325=178200N."
    },
    "n_bolts": {
      "type": "integer",
      "description": "Number of bolts. Must be >= 1."
    },
    "n_faying": {
      "type": "integer",
      "description": "Number of faying (slip) surfaces. Default 1."
    },
    "hole_factor": {
      "type": "number",
      "description": "Hole factor hf: 1.0 standard round (default), 0.85 oversized, 0.70 short-slotted perpendicular to load."
    },
    "Vu": {
      "type": "number",
      "description": "Applied shear (N). Used for utilization."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "'LRFD' (default, \u03c6=1.00) or 'ASD' (\u03a9=1.50)."
    }
  },
  "required": [
    "mu",
    "Pt",
    "n_bolts"
  ]
}
```

---

## `block_shear_capacity`

Compute block shear rupture capacity (AISC 360-22 J4.3).

Rn = min(
    0.6·Fu·Anv + Ubs·Fu·Ant,   [shear rupture + tension rupture]
    0.6·Fy·Agv + Ubs·Fu·Ant,   [shear yield  + tension rupture]
)

Ubs = 1.0 for uniform tension distribution (most connections).
Ubs = 0.5 for non-uniform (beam webs with multiple bolt rows).
Supports LRFD (φ=0.75) and ASD (Ω=2.00).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "Fu": {
      "type": "number",
      "description": "Ultimate tensile stress of material (Pa). Must be > 0."
    },
    "Fy": {
      "type": "number",
      "description": "Yield stress of material (Pa). Must be > 0."
    },
    "Agv": {
      "type": "number",
      "description": "Gross area in shear (mm\u00b2). Must be > 0."
    },
    "Anv": {
      "type": "number",
      "description": "Net area in shear (mm\u00b2). Must be > 0."
    },
    "Ant": {
      "type": "number",
      "description": "Net area in tension (mm\u00b2). Must be > 0."
    },
    "Ubs": {
      "type": "number",
      "description": "Tension stress distribution factor: 1.0 (default, uniform) or 0.5 (non-uniform). Must be in (0, 1]."
    },
    "Vu": {
      "type": "number",
      "description": "Applied force (N). Used for utilization."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "'LRFD' (default) or 'ASD'."
    }
  },
  "required": [
    "Fu",
    "Fy",
    "Agv",
    "Anv",
    "Ant"
  ]
}
```

---

## `bolt_group_eccentric`

Compute eccentric bolt group capacity ratio.

Two methods:
  'IC' (default) — Instantaneous Center of Rotation (AISC Table 7-7 approach).
  'elastic'      — Elastic Vector Method (conservative closed-form).

Applies P at eccentricity e (mm) from the bolt-group centroid.
Returns utilization ratio and governing bolt index.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "bolt_coords": {
      "type": "array",
      "description": "List of [x_mm, y_mm] coordinates for each bolt. Minimum 2 bolts required.",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "minItems": 2
    },
    "P": {
      "type": "number",
      "description": "Applied shear force (N). Must be > 0."
    },
    "e": {
      "type": "number",
      "description": "Eccentricity of P from bolt-group centroid (mm). Must be >= 0."
    },
    "method_beg": {
      "type": "string",
      "enum": [
        "IC",
        "elastic"
      ],
      "description": "'IC' (default) or 'elastic'."
    },
    "Vn_per_bolt": {
      "type": "number",
      "description": "Individual bolt design shear capacity (N). Required for absolute utilization in 'elastic' method."
    }
  },
  "required": [
    "bolt_coords",
    "P",
    "e"
  ]
}
```

---

## `fillet_weld_capacity`

Compute fillet weld group capacity (AISC 360-22 J2.4).

Rn = 0.60 × Fexx × (1 + 0.50·sin¹·⁵θ) × throat × L × n_welds

D_sixteenths: weld size in sixteenths of an inch (e.g. 5 = 5/16").
θ = angle between weld axis and load direction (0° parallel, 90° transverse).
Supports LRFD (φ=0.75) and ASD (Ω=2.00).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "D_sixteenths": {
      "type": "number",
      "description": "Weld size in sixteenths of an inch. E.g. 5 = 5/16\" weld."
    },
    "L_weld": {
      "type": "number",
      "description": "Total effective weld length (mm). Must be > 0."
    },
    "Fexx": {
      "type": "number",
      "description": "Electrode classification strength (Pa). E70 = 482.6e6 Pa."
    },
    "angle_deg": {
      "type": "number",
      "description": "Angle between weld axis and load direction (degrees, 0\u201390). 0\u00b0 = parallel (shear), 90\u00b0 = transverse (tension). Default 0."
    },
    "n_welds": {
      "type": "integer",
      "description": "Number of identical weld lines (e.g. 2 for double-sided). Default 1."
    },
    "Vu": {
      "type": "number",
      "description": "Applied load (N). Used for utilization."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "'LRFD' (default) or 'ASD'."
    }
  },
  "required": [
    "D_sixteenths",
    "L_weld",
    "Fexx"
  ]
}
```

---

## `weld_group_elastic_vector`

Elastic vector method for a general weld group under eccentric load.

Each weld segment is described by (x0,y0,x1,y1,D_sixteenths,Fexx_Pa).
The group centroid and polar moment of inertia (Iu) are computed analytically.

Returns utilization ratio and governing stress.
Supports LRFD (φ=0.75) and ASD (Ω=2.00).

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "weld_segments": {
      "type": "array",
      "description": "List of weld segments. Each element: [x0_mm, y0_mm, x1_mm, y1_mm, D_sixteenths, Fexx_Pa].",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 6,
        "maxItems": 6
      },
      "minItems": 1
    },
    "P": {
      "type": "number",
      "description": "Applied force magnitude in +y direction (N). Must be > 0."
    },
    "ex": {
      "type": "number",
      "description": "x-eccentricity of load from weld-group centroid (mm)."
    },
    "ey": {
      "type": "number",
      "description": "y-eccentricity of load from weld-group centroid (mm)."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "'LRFD' (default) or 'ASD'."
    }
  },
  "required": [
    "weld_segments",
    "P",
    "ex",
    "ey"
  ]
}
```

---

## `base_plate_bearing`

Bearing stress check for a column base plate on grout/concrete (AISC 360-22 J8).

Checks:  fp_actual = P / (B × N)  vs  fp_allow = φ × fp_prime  (LRFD)
                                    or  fp_prime / Ω            (ASD)

fp_prime is typically 0.85 × f'c (ACI 318 bearing limit).
Default φ=0.65, Ω=2.31 per AISC J8.

Errors: {ok:false, reason} for invalid inputs.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "P": {
      "type": "number",
      "description": "Column axial load (N). Must be > 0."
    },
    "B": {
      "type": "number",
      "description": "Base plate width (mm). Must be > 0."
    },
    "N": {
      "type": "number",
      "description": "Base plate length/depth (mm). Must be > 0."
    },
    "fp_prime": {
      "type": "number",
      "description": "Allowable bearing pressure (Pa). Typically 0.85 \u00d7 f'c. For f'c=28 MPa: fp_prime = 0.85 \u00d7 28e6 = 23.8e6 Pa."
    },
    "method": {
      "type": "string",
      "enum": [
        "LRFD",
        "ASD"
      ],
      "description": "'LRFD' (default, \u03c6=0.65) or 'ASD' (\u03a9=2.31)."
    }
  },
  "required": [
    "P",
    "B",
    "N",
    "fp_prime"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
