# lca_report

*Module: `kerf_lca.tools.lca_report` · Domain: lca*

## Description

Generate a Life Cycle Assessment (LCA) / embodied-carbon report for the current project. Walks the Bill of Materials (BOM), multiplies each part's mass by its ICE v3 embodied-carbon factor, and returns: (1) total embodied carbon in kg CO₂-eq, (2) per-material breakdown, (3) circularity score (0–100, based on recycled content and end-of-life recyclability). Optionally supply an explicit 'parts' list to override the project BOM.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string",
      "description": "Project UUID (defaults to current project)."
    },
    "parts": {
      "type": "array",
      "description": "Explicit BOM override. Each item: { name, material, mass_kg, quantity }. When omitted the project's BOM is read from the database.",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "material": {
            "type": "string"
          },
          "mass_kg": {
            "type": "number"
          },
          "quantity": {
            "type": "integer"
          }
        },
        "required": [
          "name"
        ]
      }
    }
  }
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="lca_report",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_lca`
