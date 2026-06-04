# facade_ifc

*Module: `kerf_bim.tools.facade_ifc` · Domain: bim*

This module registers **2** LLM tool(s):

- [`bim_parse_facade_ifc`](#bim-parse-facade-ifc)
- [`bim_facade_thermal_summary`](#bim-facade-thermal-summary)

---

## `bim_parse_facade_ifc`

Parse an IFC 4 file and extract façade elements (walls, curtain walls, windows, doors) with thermal (U-value / R-value) and structural properties (structural_class, fire_rating). Elements are grouped by IfcBuildingStorey. Returns a summary dict and optionally stores the parsed model as a project file. NOTE: IFC 4 subset parser — NOT buildingSMART certified.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string",
      "description": "UUID of the target Kerf project."
    },
    "file_blob_id": {
      "type": "string",
      "description": "Blob ID or storage key for the uploaded .ifc file."
    },
    "store_result": {
      "type": "boolean",
      "description": "If true (default), store the parsed FacadeModel summary as a project file (kind='facade_ifc') and return the file_id."
    }
  },
  "required": [
    "project_id",
    "file_blob_id"
  ]
}
```

---

## `bim_facade_thermal_summary`

Compute building-envelope thermal summary from a previously-parsed IFC façade model file (kind='facade_ifc'). Returns: total_facade_area_m2, total_opening_area_m2, window_to_wall_ratio, weighted_u_value_W_m2K, elements_with_u_value, elements_missing_u_value.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string",
      "description": "UUID of the Kerf project."
    },
    "file_id": {
      "type": "string",
      "description": "UUID of the facade_ifc file produced by bim_parse_facade_ifc."
    }
  },
  "required": [
    "project_id",
    "file_id"
  ]
}
```

---

## See also

- Package: `kerf_bim`
