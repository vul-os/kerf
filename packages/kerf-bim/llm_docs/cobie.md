# cobie

*Module: `kerf_bim.tools.cobie` · Domain: bim*

This module registers **5** LLM tool(s):

- [`bim_get_standard_template`](#bim-get-standard-template)
- [`bim_apply_property_mapping`](#bim-apply-property-mapping)
- [`bim_validate_cobie`](#bim-validate-cobie)
- [`bim_export_cobie_excel`](#bim-export-cobie-excel)
- [`bim_compute_cobie_completeness`](#bim-compute-cobie-completeness)

---

## `bim_get_standard_template`

Retrieve a built-in COBie property-mapping template by name.

COBie (Construction Operations Building information exchange) maps IFC property sets to the FM-handoff spreadsheet demanded by facility managers.

Available templates:
  • standard          — COBie 2.4 generic (IFC pset→COBie column)
  • federal_us        — US Federal (GSA/USACE) extended psets
  • uk_ukgbc          — UK / UKGBC BS1192-4 lifecycle extension
  • singapore_corenet — Singapore BCA CorNet e-Submission variant

Returns the template as a JSON dict with 'template_name' and 'mappings'.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "name": {
      "type": "string",
      "description": "Template name: 'standard' | 'federal_us' | 'uk_ukgbc' | 'singapore_corenet'."
    }
  },
  "required": [
    "name"
  ]
}
```

---

## `bim_apply_property_mapping`

Map IFC property sets to a full COBie deliverable (all 18 sheets).

Supply:
  • ifc_data      — normalised IFC model dict (property_sets + elements)
  • template_name — one of the 4 built-in templates, or omit for 'standard'

ifc_data shape:
  {
    'created_by': 'user@example.com',
    'property_sets': {'PsetName': {'PropName': 'value'}},
    'elements': [
      {'ifc_class': 'IfcSpace', 'name': 'Room 101',
       'property_sets': {'Pset_SpaceCommon': {'GrossFloorArea': '42.0'}}}
    ]
  }

Returns a summary: sheet names, row counts, completeness score.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ifc_data": {
      "type": "object",
      "description": "Normalised IFC model dict."
    },
    "template_name": {
      "type": "string",
      "description": "Built-in template name (default: 'standard').",
      "default": "standard"
    }
  },
  "required": [
    "ifc_data"
  ]
}
```

---

## `bim_validate_cobie`

Validate a COBie deliverable for COBie 2.4 compliance.

Checks:
  • All 18 COBie sheets present
  • Required columns present per sheet
  • GUIDs / Emails unique within their sheet

Returns {'valid': true} or {'valid': false, 'errors': [...]}

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ifc_data": {
      "type": "object",
      "description": "Normalised IFC model dict (same shape as bim_apply_property_mapping)."
    },
    "template_name": {
      "type": "string",
      "description": "Template to apply before validating (default: 'standard').",
      "default": "standard"
    }
  },
  "required": [
    "ifc_data"
  ]
}
```

---

## `bim_export_cobie_excel`

Export a COBie deliverable to an .xlsx file.

Applies the specified template to ifc_data, then writes an Excel workbook with one tab per COBie sheet.  Falls back to per-sheet .csv files if openpyxl is not installed.

Returns the path of the written file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ifc_data": {
      "type": "object",
      "description": "Normalised IFC model dict."
    },
    "output_path": {
      "type": "string",
      "description": "Destination .xlsx file path."
    },
    "template_name": {
      "type": "string",
      "description": "Template to apply (default: 'standard').",
      "default": "standard"
    }
  },
  "required": [
    "ifc_data",
    "output_path"
  ]
}
```

---

## `bim_compute_cobie_completeness`

Compute the COBie completeness score for an IFC dataset.

Returns the fraction (0.0–1.0) and percentage of required COBie columns that have at least one populated value in the deliverable produced by applying the specified template to ifc_data.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "ifc_data": {
      "type": "object",
      "description": "Normalised IFC model dict."
    },
    "template_name": {
      "type": "string",
      "description": "Template to apply (default: 'standard').",
      "default": "standard"
    }
  },
  "required": [
    "ifc_data"
  ]
}
```

---

## See also

- Package: `kerf_bim`
