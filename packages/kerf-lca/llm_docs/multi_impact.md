# multi_impact

*Module: `kerf_lca.tools.multi_impact` · Domain: lca*

## Description

Compute multi-impact characterisation beyond GWP100 for a product material breakdown. Categories: acidification (kg SO₂-eq, CML 2002), eutrophication (kg PO₄-eq, CML 2002), human toxicity (CTUh, USEtox), water consumption (m³), particulate matter (kg PM2.5-eq, ReCiPe 2016).

## Input schema

```json
{
  "type": "object",
  "required": [
    "product_breakdown"
  ],
  "properties": {
    "product_breakdown": {
      "type": "array",
      "description": "List of {material_id, mass_kg} items.",
      "items": {
        "type": "object",
        "required": [
          "material_id",
          "mass_kg"
        ],
        "properties": {
          "material_id": {
            "type": "string"
          },
          "mass_kg": {
            "type": "number"
          }
        }
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
    tool_name="multi_impact",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_lca`
