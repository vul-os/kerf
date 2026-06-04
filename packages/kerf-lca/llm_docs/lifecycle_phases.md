# lifecycle_phases

*Module: `kerf_lca.tools.lifecycle_phases` · Domain: lca*

## Description

Compute a full ISO 14040/44 lifecycle GWP assessment across all phases: Phase 1 cradle-to-gate (supply an existing lca_report result), Phase 2 use-phase operational energy, Phase 3 transport, and Phase 4 end-of-life (landfill / incinerate / recycle with allocation). Returns total lifecycle GWP (kg CO₂-eq) and per-phase breakdown.

## Input schema

```json
{
  "type": "object",
  "required": [
    "product"
  ],
  "properties": {
    "product": {
      "type": "string",
      "description": "Product or assembly name."
    },
    "cradle_to_gate_gwp": {
      "type": "number",
      "description": "Phase 1 embodied GWP from lca_report (kg CO\u2082-eq)."
    },
    "functional_unit": {
      "type": "string",
      "description": "Functional unit declaration, e.g. '1 kg bracket'."
    },
    "use_phase": {
      "type": "object",
      "description": "Use-phase energy arguments.",
      "properties": {
        "lifetime_years": {
          "type": "number"
        },
        "annual_energy_kWh": {
          "type": "number"
        },
        "region": {
          "type": "string"
        },
        "grid_emission_factor_kgCO2_per_kWh": {
          "type": "number"
        }
      },
      "required": [
        "lifetime_years",
        "annual_energy_kWh"
      ]
    },
    "transport": {
      "type": "object",
      "description": "Transport-phase arguments.",
      "properties": {
        "mass_kg": {
          "type": "number"
        },
        "distance_km": {
          "type": "number"
        },
        "mode": {
          "type": "string",
          "enum": [
            "truck",
            "rail",
            "sea",
            "air"
          ]
        }
      },
      "required": [
        "mass_kg",
        "distance_km"
      ]
    },
    "eol": {
      "type": "object",
      "description": "End-of-life arguments.",
      "properties": {
        "mass_kg": {
          "type": "number"
        },
        "scenario": {
          "type": "string",
          "enum": [
            "landfill",
            "incinerate",
            "recycle"
          ]
        },
        "material_gwp_factor": {
          "type": "number"
        },
        "recycle_allocation": {
          "type": "number"
        }
      },
      "required": [
        "mass_kg",
        "scenario"
      ]
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="lifecycle_phases",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_lca`
