# autoplace

*Module: `kerf_electronics.autoplace.tools` · Domain: electronics*

This module registers **5** LLM tool(s):

- [`auto_decouple`](#auto-decouple)
- [`thermal_via_array`](#thermal-via-array)
- [`mounting_hole_keepout`](#mounting-hole-keepout)
- [`power_plane_relief`](#power-plane-relief)
- [`bypass_cap_recommendation`](#bypass-cap-recommendation)

---

## `auto_decouple`

Place one decoupling capacitor per VCC/VDD pin of each IC footprint on the board. Each cap is positioned at most 2 mm from the VCC pin, along the vector toward the nearest GND pin of the same IC. Short VCC→cap and cap→GND trace segments are generated. Returns the list of placed cap objects and trace segments ready to merge into the CircuitJSON board.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "board": {
      "description": "CircuitJSON board element or array. Used read-only as context (dimensions, existing traces).",
      "oneOf": [
        {
          "type": "object"
        },
        {
          "type": "array",
          "items": {
            "type": "object"
          }
        }
      ]
    },
    "ic_footprints": {
      "type": "array",
      "description": "List of IC component dicts. Each must have 'refdes', 'x', 'y', and a 'pads' list. Each pad needs 'net_name' (or 'pin_name'/'net_id') plus 'x', 'y' offsets relative to the component origin.",
      "items": {
        "type": "object"
      }
    },
    "cap_value": {
      "type": "string",
      "description": "Capacitor value label (default '100nF')."
    },
    "package": {
      "type": "string",
      "description": "Package code, e.g. '0402', '0201', '0603' (default '0402').",
      "enum": [
        "0201",
        "0402",
        "0603",
        "0805",
        "1206"
      ]
    }
  },
  "required": [
    "ic_footprints"
  ]
}
```

---

## `thermal_via_array`

Place an N×M via array under an IC thermal / exposed pad for PCB heat-sinking. The array is centred on the pad. Supports 'grid' and 'staggered' lattice patterns. Returns the list of via objects and the grid dimensions used.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "board": {
      "description": "CircuitJSON board (read-only context).",
      "oneOf": [
        {
          "type": "object"
        },
        {
          "type": "array",
          "items": {
            "type": "object"
          }
        }
      ]
    },
    "pad": {
      "type": "object",
      "description": "Thermal pad dict with 'x', 'y', 'width', 'height', and 'net_name' (or 'net_id')."
    },
    "via_count": {
      "type": "integer",
      "description": "Target number of vias (actual may be slightly more to fill the grid).",
      "minimum": 1
    },
    "via_dia": {
      "type": "number",
      "description": "Via outer annular ring diameter (mm)."
    },
    "via_drill": {
      "type": "number",
      "description": "Via drill diameter (mm). Must be < via_dia."
    },
    "pattern": {
      "type": "string",
      "enum": [
        "grid",
        "staggered"
      ],
      "description": "Via arrangement: 'grid' (default) or 'staggered' offset rows."
    }
  },
  "required": [
    "pad",
    "via_count",
    "via_dia",
    "via_drill"
  ]
}
```

---

## `mounting_hole_keepout`

Generate a circular no-route / no-component keep-out zone around a PCB mounting hole. The keep-out radius equals hole_dia/2 + keepout_extra_mm (default 2.5 mm). Returns a CircuitJSON-compatible keepout polygon and the effective radius.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "board": {
      "description": "CircuitJSON board (read-only context).",
      "oneOf": [
        {
          "type": "object"
        },
        {
          "type": "array",
          "items": {
            "type": "object"
          }
        }
      ]
    },
    "hole_position": {
      "type": "object",
      "description": "Dict with 'x' and 'y' keys (mm).",
      "properties": {
        "x": {
          "type": "number"
        },
        "y": {
          "type": "number"
        }
      },
      "required": [
        "x",
        "y"
      ]
    },
    "hole_dia": {
      "type": "number",
      "description": "Mounting hole drill diameter (mm)."
    },
    "keepout_extra_mm": {
      "type": "number",
      "description": "Additional clearance beyond the hole edge (mm). Default 2.5 mm per IPC-7351 guidance."
    }
  },
  "required": [
    "hole_position",
    "hole_dia"
  ]
}
```

---

## `power_plane_relief`

Generate an anti-pad (thermal relief) cutout for a signal or power via passing through a copper power plane. The anti-pad is a circular polygon with diameter = via_outer_dia + 2 × anti_pad_mm, placed on the specified plane layer. Returns a CircuitJSON plane-cutout object.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "plane_layer": {
      "type": "string",
      "description": "Layer name of the power plane, e.g. 'inner_copper_1', 'inner_copper_2', 'bottom_copper'."
    },
    "via": {
      "type": "object",
      "description": "Via dict with 'x', 'y', 'outer_diameter' (mm), and 'net_name' (or 'net_id')."
    },
    "anti_pad_mm": {
      "type": "number",
      "description": "Clearance from via pad edge to plane edge (mm). Typical value: 0.2\u20130.5 mm."
    }
  },
  "required": [
    "plane_layer",
    "via",
    "anti_pad_mm"
  ]
}
```

---

## `bypass_cap_recommendation`

Recommend bypass / decoupling capacitor values and packages for a given IC part number. Covers common MCUs (STM32, RP2040, ESP32, ATmega), FPGAs, op-amps, LDO regulators, logic families, and ADCs. Unknown parts receive a generic 100 nF + 10 uF recommendation.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ic_part": {
      "type": "string",
      "description": "Part number or descriptive name, e.g. 'STM32F103C8', 'ATmega328P', 'AMS1117-3.3', '74HC595' (case-insensitive)."
    },
    "supply_voltage": {
      "type": "number",
      "description": "Supply voltage in volts (optional context)."
    }
  },
  "required": [
    "ic_part"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
