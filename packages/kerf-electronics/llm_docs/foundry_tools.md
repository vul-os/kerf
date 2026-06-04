# foundry_tools

*Module: `kerf_electronics.spice.foundry_tools` · Domain: electronics*

This module registers **4** LLM tool(s):

- [`electronics_bsim4_iv`](#electronics-bsim4-iv)
- [`electronics_bsim4_corner`](#electronics-bsim4-corner)
- [`electronics_generate_netlist`](#electronics-generate-netlist)
- [`electronics_parse_netlist`](#electronics-parse-netlist)

---

## `electronics_bsim4_iv`

Compute BSIM4.8 MOSFET drain current Id, transconductance gm, and gate-source capacitance Cgs at specified bias conditions. Returns Id (A), gm (S), Cgs (F), Vth (V). HONEST NOTE: BSIM4.8 first-order model (UC Berkeley, 2013); not foundry-PDK accurate; for design exploration only.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "vgs": {
      "type": "number",
      "description": "Gate-source voltage (V)"
    },
    "vds": {
      "type": "number",
      "description": "Drain-source voltage (V)"
    },
    "vbs": {
      "type": "number",
      "description": "Body-source voltage (V), default 0"
    },
    "T_celsius": {
      "type": "number",
      "description": "Temperature (\u00b0C), default 27"
    },
    "W_um": {
      "type": "number",
      "description": "Channel width (\u03bcm), default 1.0"
    },
    "L_nm": {
      "type": "number",
      "description": "Channel length (nm), default 100"
    },
    "nf": {
      "type": "integer",
      "description": "Number of gate fingers, default 1"
    },
    "model_params": {
      "type": "object",
      "description": "Optional BSIM4 parameter overrides (vth0, u0, tox, etc.)"
    }
  },
  "required": [
    "vgs",
    "vds"
  ]
}
```

---

## `electronics_bsim4_corner`

Run a PVT / Monte-Carlo corner sweep on a BSIM4 MOSFET. Sweeps all 5 standard process corners (TT/SS/FF/SF/FS), voltages ±10%, and temperatures −40/27/125°C with Pelgrom mismatch Monte-Carlo. Returns worst-case Id variation, yield estimate, and per-corner statistics. HONEST NOTE: not foundry-PDK accurate; for design exploration only.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "vgs": {
      "type": "number",
      "description": "Nominal Vgs (V)"
    },
    "vds": {
      "type": "number",
      "description": "Nominal Vds (V)"
    },
    "vbs": {
      "type": "number",
      "description": "Body-source voltage (V), default 0"
    },
    "W_um": {
      "type": "number",
      "description": "Channel width (\u03bcm), default 1.0"
    },
    "L_nm": {
      "type": "number",
      "description": "Channel length (nm), default 100"
    },
    "monte_carlo_iterations": {
      "type": "integer",
      "description": "MC iterations per (corner, V, T) point, default 100"
    },
    "spec_min_id_uA": {
      "type": "number",
      "description": "Minimum Id spec for yield estimation (\u03bcA); omit for no spec"
    },
    "rng_seed": {
      "type": "integer",
      "description": "RNG seed for reproducibility"
    }
  },
  "required": [
    "vgs",
    "vds"
  ]
}
```

---

## `electronics_generate_netlist`

Generate a SPICE netlist from a schematic graph description. Supports Cadence Spectre, ngspice, and HSPICE dialects. Returns the netlist as a string. HONEST NOTE: Syntax-correct but requires foundry device model files for simulation accuracy. Not for tape-out sign-off.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "title": {
      "type": "string",
      "description": "Netlist title"
    },
    "dialect": {
      "type": "string",
      "enum": [
        "spectre",
        "ngspice",
        "hspice"
      ],
      "description": "Simulator dialect, default 'ngspice'"
    },
    "devices": {
      "type": "array",
      "description": "List of device objects",
      "items": {
        "type": "object",
        "properties": {
          "device_id": {
            "type": "string"
          },
          "kind": {
            "type": "string"
          },
          "pins": {
            "type": "array",
            "items": {
              "type": "string"
            }
          },
          "parameters": {
            "type": "object"
          },
          "model_name": {
            "type": "string"
          }
        },
        "required": [
          "device_id",
          "kind",
          "pins"
        ]
      }
    },
    "nodes": {
      "type": "array",
      "description": "Optional list of named nodes",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "voltage": {
            "type": "string"
          }
        }
      }
    }
  },
  "required": [
    "devices"
  ]
}
```

---

## `electronics_parse_netlist`

Parse a SPICE netlist string into a structured schematic graph (JSON). Supports Cadence Spectre, ngspice, and HSPICE syntax. Useful for round-trip verification and netlist inspection.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "netlist": {
      "type": "string",
      "description": "SPICE netlist text"
    },
    "dialect": {
      "type": "string",
      "enum": [
        "spectre",
        "ngspice",
        "hspice"
      ],
      "description": "Simulator dialect, default 'ngspice'"
    }
  },
  "required": [
    "netlist"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
