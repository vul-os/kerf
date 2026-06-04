# embodied_carbon

*Module: `kerf_lca.tools.embodied_carbon` · Domain: lca*

This module registers **2** LLM tool(s):

- [`lca_lookup_material`](#lca-lookup-material)
- [`lca_compute_embodied_carbon`](#lca-compute-embodied-carbon)

---

## `lca_lookup_material`

Look up a material in the ICE v3.0 embodied-carbon database (Hammond & Jones, University of Bath, 2019). Returns the material's embodied carbon (kg CO2-eq/kg, cradle-to-gate), recycling factor, end-of-life carbon, and ICE v3 source citation. Data is ICE v3 open data — NOT Ecoinvent (license-restricted). Use this before compute_embodied_carbon to verify a material is supported.

### Input schema

```json
{
  "type": "object",
  "required": [
    "material_name"
  ],
  "properties": {
    "material_name": {
      "type": "string",
      "description": "Material name or key. Accepts canonical keys (e.g. 'steel-virgin', 'aluminum-recycled', 'concrete-mix') and common aliases (e.g. 'steel', 'aluminium', 'concrete', 'nylon', 'abs', 'carbon fiber', 'CFRP', 'plywood'). Case-insensitive."
    }
  }
}
```

---

## `lca_compute_embodied_carbon`

Compute cradle-to-gate embodied carbon and end-of-life carbon for a single part using ICE v3.0 reference factors. Returns: embodied_co2 (kg CO2-eq), end_of_life_co2 (kg CO2-eq), source citation ('ICE v3'), and caveats. Data is ICE v3 open data — NOT Ecoinvent (license-restricted). For multi-part BOMs use the 'lca_report' tool instead.

### Input schema

```json
{
  "type": "object",
  "required": [
    "part_mass_kg",
    "material_name"
  ],
  "properties": {
    "part_mass_kg": {
      "type": "number",
      "description": "Mass of the part in kilograms (must be > 0)."
    },
    "material_name": {
      "type": "string",
      "description": "Material name or key. Accepts canonical keys and aliases. Examples: 'steel-virgin', 'aluminum-recycled', 'concrete-mix', 'nylon-6', 'carbon-fiber', 'polycarbonate'. Case-insensitive."
    }
  }
}
```

---

## See also

- Package: `kerf_lca`
