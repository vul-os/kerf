# battery

*Module: `kerf_electronics.battery.tools` · Domain: electronics*

This module registers **4** LLM tool(s):

- [`battery_size_pack`](#battery-size-pack)
- [`battery_runtime`](#battery-runtime)
- [`battery_charge_time`](#battery-charge-time)
- [`battery_report`](#battery-report)

---

## `battery_size_pack`

Size a battery pack from a target voltage and capacity given a single-cell spec. Computes the minimum series (n_s) and parallel (n_p) cell count, total cells, actual pack voltage, capacity, energy, and (when cell dimensions are given) pack mass and volume. Returns warnings when a cell C-rate check fails or capacity is marginal. Input shape: { target_voltage_v, target_capacity_ah, cell_voltage_v, cell_capacity_ah, cell_mass_g?, cell_volume_cm3?, cell_r_int_ohm?, cell_max_discharge_c? }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "target_voltage_v": {
      "type": "number",
      "description": "Desired pack nominal voltage (V)."
    },
    "target_capacity_ah": {
      "type": "number",
      "description": "Desired pack capacity (Ah)."
    },
    "cell_voltage_v": {
      "type": "number",
      "description": "Cell nominal voltage (V) \u2014 e.g. 3.6 for Li-ion 18650."
    },
    "cell_capacity_ah": {
      "type": "number",
      "description": "Cell rated capacity (Ah) \u2014 e.g. 3.0 for a 3 Ah cell."
    },
    "cell_mass_g": {
      "type": "number",
      "description": "Single-cell mass (g). Optional; enables pack_mass_g output."
    },
    "cell_volume_cm3": {
      "type": "number",
      "description": "Single-cell volume (cm\u00b3). Optional; enables pack_volume_cm3."
    },
    "cell_r_int_ohm": {
      "type": "number",
      "description": "Cell internal resistance (\u03a9). Optional; enables pack_r_int_ohm."
    },
    "cell_max_discharge_c": {
      "type": "number",
      "description": "Cell max continuous discharge C-rate. Optional; enables C-rate warning."
    }
  },
  "required": [
    "target_voltage_v",
    "target_capacity_ah",
    "cell_voltage_v",
    "cell_capacity_ah"
  ]
}
```

---

## `battery_runtime`

Estimate battery pack runtime from a multi-step load profile. Applies Peukert correction (k > 1 reduces effective capacity at high currents) and respects a depth-of-discharge (DoD) limit. Returns per-step actual duration, total runtime, energy delivered, and an 'exhausted' flag when the pack is depleted before the profile ends. Adds a warning when any step exceeds cell_max_discharge_c. Input shape: { pack_capacity_ah, pack_voltage_v, load_profile, peukert_k?, dod_limit?, cell_max_discharge_c?, pack_r_int_ohm? } load_profile items: { power_W, duration_s }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pack_capacity_ah": {
      "type": "number",
      "description": "Rated pack capacity (Ah)."
    },
    "pack_voltage_v": {
      "type": "number",
      "description": "Pack nominal voltage (V)."
    },
    "load_profile": {
      "type": "array",
      "description": "Ordered list of load steps.",
      "items": {
        "type": "object",
        "properties": {
          "power_W": {
            "type": "number",
            "description": "Power draw for this step (W)."
          },
          "duration_s": {
            "type": "number",
            "description": "Requested duration for this step (s)."
          }
        },
        "required": [
          "power_W",
          "duration_s"
        ]
      }
    },
    "peukert_k": {
      "type": "number",
      "description": "Peukert exponent (default 1.1). Li-ion: 1.05\u20131.15; lead-acid: 1.2\u20131.8. Set to 1.0 for ideal cell (no correction)."
    },
    "dod_limit": {
      "type": "number",
      "description": "Depth-of-discharge limit (0 < dod_limit <= 1.0; default 0.8). Fraction of rated capacity that is usable."
    },
    "cell_max_discharge_c": {
      "type": "number",
      "description": "Max cell C-rate; triggers a warning when exceeded."
    },
    "pack_r_int_ohm": {
      "type": "number",
      "description": "Pack internal resistance (\u03a9); used for voltage-drop report."
    }
  },
  "required": [
    "pack_capacity_ah",
    "pack_voltage_v",
    "load_profile"
  ]
}
```

---

## `battery_charge_time`

Estimate battery pack charge time using a simplified CC-CV model. CC phase charges at charge_c_rate × Q_rated until ~80% SoC; CV tail adds ~20% of CC time for full top-up. Returns cc_time_h, cv_tail_h, total_time_h, and total_time_min. Input shape: { pack_capacity_ah, charge_c_rate?, dod_at_start? }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pack_capacity_ah": {
      "type": "number",
      "description": "Rated pack capacity (Ah)."
    },
    "charge_c_rate": {
      "type": "number",
      "description": "Charge C-rate (default 0.5 = C/2). E.g. 1.0 = 1C charge, 0.5 = C/2."
    },
    "dod_at_start": {
      "type": "number",
      "description": "Depth of discharge at start of charging (default 0.8). 0.8 means the pack is 80% depleted."
    }
  },
  "required": [
    "pack_capacity_ah"
  ]
}
```

---

## `battery_report`

Combined battery pack report: sizing + runtime + charge time + thermal rise. Accepts cell spec and a load profile; computes pack configuration, runtime with Peukert correction, charge-time (CC-CV), and (when cell_r_int_ohm + cell_mass_g are given) adiabatic thermal rise. Warnings are aggregated from all sub-calculations. Input shape: { target_voltage_v, target_capacity_ah, cell_voltage_v, cell_capacity_ah, load_profile, peukert_k?, dod_limit?, charge_c_rate?, cell_mass_g?, cell_volume_cm3?, cell_r_int_ohm?, cell_max_discharge_c? }

### Input schema

```json
{
  "type": "object",
  "properties": {
    "target_voltage_v": {
      "type": "number"
    },
    "target_capacity_ah": {
      "type": "number"
    },
    "cell_voltage_v": {
      "type": "number"
    },
    "cell_capacity_ah": {
      "type": "number"
    },
    "load_profile": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "power_W": {
            "type": "number"
          },
          "duration_s": {
            "type": "number"
          }
        },
        "required": [
          "power_W",
          "duration_s"
        ]
      }
    },
    "peukert_k": {
      "type": "number"
    },
    "dod_limit": {
      "type": "number"
    },
    "charge_c_rate": {
      "type": "number"
    },
    "cell_mass_g": {
      "type": "number"
    },
    "cell_volume_cm3": {
      "type": "number"
    },
    "cell_r_int_ohm": {
      "type": "number"
    },
    "cell_max_discharge_c": {
      "type": "number"
    }
  },
  "required": [
    "target_voltage_v",
    "target_capacity_ah",
    "cell_voltage_v",
    "cell_capacity_ah",
    "load_profile"
  ]
}
```

---

## See also

- Package: `kerf_electronics`
