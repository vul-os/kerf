# cncfeeds

*Module: `kerf_cad_core.cncfeeds.tools` · Domain: cad*

This module registers **13** LLM tool(s):

- [`cnc_spindle_rpm`](#cnc-spindle-rpm)
- [`cnc_feed_rate`](#cnc-feed-rate)
- [`cnc_mrr_milling`](#cnc-mrr-milling)
- [`cnc_mrr_drilling`](#cnc-mrr-drilling)
- [`cnc_mrr_turning`](#cnc-mrr-turning)
- [`cnc_cutting_power`](#cnc-cutting-power)
- [`cnc_tangential_force`](#cnc-tangential-force)
- [`cnc_chip_thinning`](#cnc-chip-thinning)
- [`cnc_corrected_chip_load`](#cnc-corrected-chip-load)
- [`cnc_tool_deflection`](#cnc-tool-deflection)
- [`cnc_surface_finish_ra`](#cnc-surface-finish-ra)
- [`cnc_drill_thrust_torque`](#cnc-drill-thrust-torque)
- [`cnc_tapping_speed`](#cnc-tapping-speed)

---

## `cnc_spindle_rpm`

Compute spindle speed (RPM) from cutting speed and cutter or workpiece diameter.

Formula: n = 1000 × vc / (π × D)

Returns rpm.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "vc": {
      "type": "number",
      "description": "Cutting speed (m/min). Must be > 0."
    },
    "diameter": {
      "type": "number",
      "description": "Cutter or workpiece diameter (mm). Must be > 0."
    }
  },
  "required": [
    "vc",
    "diameter"
  ]
}
```

---

## `cnc_feed_rate`

Compute table feed rate (mm/min) from chip load, number of teeth, and spindle speed.

Formula: Vf = fz × z × n

Returns feed_mm_min.  Flags chip_load_low / chip_load_high in warnings.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "chip_load": {
      "type": "number",
      "description": "Chip load per tooth fz (mm/tooth). Must be > 0."
    },
    "teeth": {
      "type": "integer",
      "description": "Number of cutter teeth / flutes. Must be >= 1."
    },
    "rpm": {
      "type": "number",
      "description": "Spindle speed (rev/min). Must be > 0."
    }
  },
  "required": [
    "chip_load",
    "teeth",
    "rpm"
  ]
}
```

---

## `cnc_mrr_milling`

Compute material-removal rate (MRR) for milling operations.

Formula: Q = ae × ap × Vf   [mm³/min]

Returns mrr_mm3_min.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "width": {
      "type": "number",
      "description": "Radial engagement / width of cut ae (mm). Must be > 0."
    },
    "depth": {
      "type": "number",
      "description": "Axial depth of cut ap (mm). Must be > 0."
    },
    "feed_mm_min": {
      "type": "number",
      "description": "Table feed rate Vf (mm/min). Must be > 0."
    }
  },
  "required": [
    "width",
    "depth",
    "feed_mm_min"
  ]
}
```

---

## `cnc_mrr_drilling`

Compute material-removal rate (MRR) for drilling.

Formula: Q = (π/4) × D² × fn × n   [mm³/min]

Returns mrr_mm3_min and feed_mm_min.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "diameter": {
      "type": "number",
      "description": "Drill diameter D (mm). Must be > 0."
    },
    "feed_per_rev": {
      "type": "number",
      "description": "Feed per revolution fn (mm/rev). Must be > 0."
    },
    "rpm": {
      "type": "number",
      "description": "Spindle speed (rev/min). Must be > 0."
    }
  },
  "required": [
    "diameter",
    "feed_per_rev",
    "rpm"
  ]
}
```

---

## `cnc_mrr_turning`

Compute material-removal rate (MRR) for turning (external or internal).

Formula: Q = ap × fn × vc × 1000   [mm³/min]

Returns mrr_mm3_min.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "depth_of_cut": {
      "type": "number",
      "description": "Radial depth of cut ap (mm). Must be > 0."
    },
    "feed_per_rev": {
      "type": "number",
      "description": "Feed per revolution fn (mm/rev). Must be > 0."
    },
    "vc": {
      "type": "number",
      "description": "Cutting speed vc (m/min). Must be > 0."
    }
  },
  "required": [
    "depth_of_cut",
    "feed_per_rev",
    "vc"
  ]
}
```

---

## `cnc_cutting_power`

Compute cutting power (W) and spindle torque (N·m) from MRR and specific cutting energy Kc.

Formula: Pc = kc × Q / 60000   [W]; Ps = Pc / η

Material Kc reference values (N/mm²): alloy_steel: 2600; aluminum_6061: 700; aluminum_7075: 800; brass: 1000; bronze: 1200; copper: 1100; ductile_iron: 1500; duplex_stainless: 2400; grey_cast_iron: 1100; hastelloy: 3800; inconel_718: 4000; medium_carbon_steel: 2200; mild_steel: 1800; stainless_304: 2000; stainless_316: 2100; titanium_ti6al4v: 2800; tool_steel: 3200.

Flags over_power if spindle_power_W exceeds machine_power_W.  Returns cutting_power_W, spindle_power_W, and optionally torque_Nm.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "mrr": {
      "type": "number",
      "description": "Material-removal rate Q (mm\u00b3/min). Must be > 0."
    },
    "kc": {
      "type": "number",
      "description": "Specific cutting energy (N/mm\u00b2). Must be > 0. Use MATERIAL_KC table as reference."
    },
    "efficiency": {
      "type": "number",
      "description": "Spindle mechanical efficiency \u03b7 (default 0.85). Range (0, 1]."
    },
    "machine_power_W": {
      "type": "number",
      "description": "Machine spindle rated power (W, default 7500). Used for over_power warning."
    },
    "rpm": {
      "type": "number",
      "description": "Spindle speed (rev/min). Optional \u2014 required for torque calculation."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Cutter diameter (mm). Optional \u2014 required for torque calculation."
    }
  },
  "required": [
    "mrr",
    "kc"
  ]
}
```

---

## `cnc_tangential_force`

Compute tangential (main) cutting force Ft from specific cutting energy.

Formula: Ft = kc × fz × ap × ae   [N]

Returns tangential_N.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "kc": {
      "type": "number",
      "description": "Specific cutting energy (N/mm\u00b2). Must be > 0."
    },
    "chip_load": {
      "type": "number",
      "description": "Chip load fz (mm/tooth). Must be > 0."
    },
    "depth_of_cut": {
      "type": "number",
      "description": "Axial depth of cut ap (mm). Must be > 0."
    },
    "width_of_cut": {
      "type": "number",
      "description": "Width of cut / radial engagement ae (mm, default 1.0). Must be > 0."
    }
  },
  "required": [
    "kc",
    "chip_load",
    "depth_of_cut"
  ]
}
```

---

## `cnc_chip_thinning`

Compute the chip-thinning factor (CTF) for radial engagement < 50%.

When ae < D/2, actual chip thickness < programmed chip load.
Formula: CTF = D / (2 × √(ae × (D − ae)))   when ae < D/2;
         CTF = 1.0 otherwise.

Flags chip_thinning_severe if ae/D < 0.05.  Returns ctf and ae_over_D.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "radial_engagement": {
      "type": "number",
      "description": "Radial engagement ae (mm). Must be > 0 and <= diameter."
    },
    "diameter": {
      "type": "number",
      "description": "Cutter diameter D (mm). Must be > 0."
    }
  },
  "required": [
    "radial_engagement",
    "diameter"
  ]
}
```

---

## `cnc_corrected_chip_load`

Compute the programmed chip load that accounts for chip thinning.

programmed_chip_load = target_chip_load × CTF

Returns programmed_chip_load_mm and ctf.  Flags chip_load_low / chip_load_high / chip_thinning_severe.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "nominal_chip_load": {
      "type": "number",
      "description": "Target actual chip thickness (mm/tooth). Must be > 0."
    },
    "ae": {
      "type": "number",
      "description": "Radial engagement ae (mm). Must be > 0 and <= diameter."
    },
    "diameter": {
      "type": "number",
      "description": "Cutter diameter (mm). Must be > 0."
    }
  },
  "required": [
    "nominal_chip_load",
    "ae",
    "diameter"
  ]
}
```

---

## `cnc_tool_deflection`

Compute cantilever tool deflection and maximum safe stickout.

Models tool shank as cantilever beam: δ = F × L³ / (3 × EI)

Returns deflection_mm and max_stickout_mm.  Flags excessive_deflection if δ > 0.025 mm or stickout > 4× diameter.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "force": {
      "type": "number",
      "description": "Transverse cutting force at tool tip (N). Must be > 0."
    },
    "overhang": {
      "type": "number",
      "description": "Tool stickout from spindle face (mm). Must be > 0."
    },
    "diameter": {
      "type": "number",
      "description": "Shank diameter (mm). Must be > 0."
    },
    "E_GPa": {
      "type": "number",
      "description": "Young's modulus of shank material (GPa, default 600 for solid carbide). Steel/HSS \u2248 210 GPa."
    }
  },
  "required": [
    "force",
    "overhang",
    "diameter"
  ]
}
```

---

## `cnc_surface_finish_ra`

Estimate theoretical surface roughness Ra from feed per revolution and tool nose radius.

Formula (Machinery's Handbook): Ra ≈ fn² / (32 × r_ε)   [mm → µm]

Returns Ra_um and Rz_um.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "feed_per_rev": {
      "type": "number",
      "description": "Feed per revolution fn (mm/rev). Must be > 0."
    },
    "nose_radius": {
      "type": "number",
      "description": "Tool nose radius r_\u03b5 (mm). Must be > 0."
    }
  },
  "required": [
    "feed_per_rev",
    "nose_radius"
  ]
}
```

---

## `cnc_drill_thrust_torque`

Compute drilling thrust force (N) and torque (N·m) from cutting parameters.

Formulas (Sandvik / Machinery's Handbook):
  Thrust: Ff = kc × fn × (D/2) × sin(κ)       [N]
  Torque: Mc = kc × fn × D² / 8 / 1000         [N·m]
  where κ = drill_point_angle / 2.

Returns thrust_N and torque_Nm.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "diameter": {
      "type": "number",
      "description": "Drill diameter D (mm). Must be > 0."
    },
    "feed_per_rev": {
      "type": "number",
      "description": "Feed per revolution fn (mm/rev). Must be > 0."
    },
    "kc": {
      "type": "number",
      "description": "Specific cutting energy (N/mm\u00b2). Must be > 0."
    },
    "drill_point_angle": {
      "type": "number",
      "description": "Included drill point angle (degrees, default 118\u00b0). Range (0, 180)."
    }
  },
  "required": [
    "diameter",
    "feed_per_rev",
    "kc"
  ]
}
```

---

## `cnc_tapping_speed`

Compute the required axial feed rate for rigid (synchronised) tapping.

Formula: Vf = p × n   [mm/min]

The CNC controller must synchronise spindle rotation to this feed to cut the correct thread pitch.  Returns feed_mm_min.  Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pitch": {
      "type": "number",
      "description": "Thread pitch p (mm/rev). Must be > 0. Metric: pitch in mm (e.g. M8\u00d71.25 \u2192 1.25). Unified (UNC/UNF): 25.4 / TPI."
    },
    "rpm": {
      "type": "number",
      "description": "Spindle speed (rev/min). Must be > 0."
    }
  },
  "required": [
    "pitch",
    "rpm"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
