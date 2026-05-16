# Material Selection (Ashby Method)

Pure-Python Ashby-style material selection tools backed by an in-memory
engineering materials database. No OCC dependency. No DB write.

---

## When to use

Use these tools when the user asks about choosing a material, comparing
materials, material properties (Young's modulus, yield strength, density,
thermal conductivity, CTE), Ashby charts, merit indices, specific strength,
specific stiffness, or material constraints.

Keywords: material selection, Ashby, materials database, specific stiffness,
specific strength, light beam, yield strength, Young's modulus, density,
thermal conductivity, CTE, aluminium, steel, titanium, CFRP, composite,
stainless, polymer, ceramic, cast iron, merit index, material comparison.

---

## Tools

### `matsel_list`

List all engineering materials in the database, optionally filtered by family.

**Input:** `family` (optional) — one of: `steel`, `stainless_steel`, `aluminium`,
`titanium`, `magnesium`, `polymer`, `composite`, `wood`, `ceramic`, `cast_iron`, `copper`

**Returns:** list of canonical material names, count

---

### `matsel_get`

Look up a single material by canonical name to retrieve all properties.

Properties returned: density (kg/m³), E (GPa), sigma_y/sigma_uts/sigma_e (MPa),
thermal conductivity k (W/m·K), CTE (µm/m·K), T_max (°C), cost_rel,
and computed Ashby indices (specific_stiffness, specific_strength,
light_stiff_beam, light_strong_plate, cost_per_stiffness).

**Input:** `name` (required) — e.g. `'AISI_4140_QT'`, `'Al_7075_T6'`, `'Ti_6Al4V'`

**Returns:** full property dict, or `{ok: false, reason}` if not found (lists available names)

---

### `matsel_filter`

Filter materials by min/max property constraints.

Filterable properties: `density`, `E`, `sigma_y`, `sigma_uts`, `sigma_e`,
`k`, `CTE`, `T_max`, `cost_rel`, and all Ashby indices.

**Input:**
```json
{
  "constraints": {
    "density": {"max": 3000},
    "E": {"min": 50},
    "sigma_y": {"min": 200}
  }
}
```

**Returns:** list of matching material names, count, warnings for empty sets

---

### `matsel_select`

Ashby-style selection: filter by constraints then rank by merit index.

Available objectives: `specific_stiffness` (E/ρ), `specific_strength` (σy/ρ),
`light_stiff_beam` (E^0.5/ρ), `light_strong_plate` (σy^(2/3)/ρ),
`cost_per_stiffness` (cost·ρ/E), or any base property.

**Input:** `constraints` (required, same syntax as matsel_filter); `objective` (default `'specific_stiffness'`); `top_n` (default 10)

**Returns:** ranked list with rank, name, index value, and key properties

---

## Example

```
1. matsel_list  family:"aluminium"
   → ["Al_1100", "Al_2024_T3", "Al_6061_T6", "Al_7075_T6", ...]

2. matsel_filter  constraints:{"density":{"max":3000},"sigma_y":{"min":400}}
   → ["Al_7075_T6", "Ti_6Al4V", "CFRP_UD_0deg", ...]

3. matsel_select  constraints:{"density":{"max":3000},"sigma_y":{"min":400}}
                  objective:"specific_strength"  top_n:5
   → [#1 CFRP_UD_0deg index:2.3e5, #2 Ti_6Al4V index:1.01e5, ...]

4. matsel_get  name:"Ti_6Al4V"
   → {density:4430, E:114, sigma_y:880, sigma_uts:950,
      specific_strength:198643, ...}
```
