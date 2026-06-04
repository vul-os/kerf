# piping_advanced_tools

*Module: `kerf_cad_core.piping.piping_advanced_tools` · Domain: cad*

This module registers **3** LLM tool(s):

- [`pipe_component_catalog_query`](#pipe-component-catalog-query)
- [`pipe_run_bom`](#pipe-run-bom)
- [`plant_federation_clash`](#plant-federation-clash)

---

## `pipe_component_catalog_query`

Query the built-in ASME B16.5 / B16.9 / API 6D pipe component catalogue.

Supports filtering by:
  component_type   — 'flange' | 'elbow' | 'tee' | 'reducer' | 'valve' | 'cap' | 'cross'
  catalog_standard — 'ASME B16.5' | 'ASME B16.9' | 'API 6D'
  nominal_size_in  — NPS in inches (float), e.g. 4.0, 6.0, 12.0
  pressure_class_psi — 150 | 300 | 600 | 900 | 1500 | 2500
  schedule         — 'SCH40' | 'SCH80' | 'SCH160' | 'XXS'

Returns: {ok:true, count, components:[{component_id, ...}]}
Errors:  {ok:false, reason}

References: ASME B16.5-2020, ASME B16.9-2018, API Spec 6D-2014.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "component_type": {
      "type": "string",
      "description": "Filter by type: flange | elbow | tee | reducer | valve | cap | cross"
    },
    "catalog_standard": {
      "type": "string",
      "description": "Filter by standard: 'ASME B16.5' | 'ASME B16.9' | 'API 6D'"
    },
    "nominal_size_in": {
      "type": "number",
      "description": "NPS in inches, e.g. 4.0"
    },
    "pressure_class_psi": {
      "type": "integer",
      "description": "Pressure class: 150 | 300 | 600 | 900 | 1500 | 2500"
    },
    "schedule": {
      "type": "string",
      "description": "Pipe schedule: SCH40 | SCH80 | SCH160 | XXS"
    }
  },
  "required": []
}
```

---

## `pipe_run_bom`

Compute a bill of materials (BOM) for a piping run.

Each pipe_segment must have:
  from (str), to (str), size_in (float), schedule (str), length_m (float)
  material (str, optional), n_elbows (int, optional), n_flanges (int, optional)

Flanges are matched from the ASME B16.5 catalogue; elbows from ASME B16.9.
HONEST: budgetary estimate only — production BOM needs vendor quotes.

Returns: {ok:true, total_weight_kg, total_cost_usd, line_items}

References: ASME B16.5-2020, ASME B16.9-2018, ASME B36.10M-2018.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "pipe_segments": {
      "type": "array",
      "description": "List of pipe segment dicts",
      "items": {
        "type": "object",
        "properties": {
          "from": {
            "type": "string"
          },
          "to": {
            "type": "string"
          },
          "size_in": {
            "type": "number"
          },
          "schedule": {
            "type": "string"
          },
          "length_m": {
            "type": "number"
          },
          "material": {
            "type": "string"
          },
          "n_elbows": {
            "type": "integer"
          },
          "n_flanges": {
            "type": "integer"
          }
        },
        "required": [
          "size_in",
          "schedule",
          "length_m"
        ]
      }
    }
  },
  "required": [
    "pipe_segments"
  ]
}
```

---

## `plant_federation_clash`

Run cross-discipline clash detection on a federated plant model.

Accepts a list of discipline submodels (each with element bounding boxes).
Returns all pairs of elements from different disciplines whose bounding boxes overlap (AABB intersection).

Also performs coordinate system consistency checking per BS 1192-4:2014.

Returns: {ok:true, clash_count, clashes:[...], warnings:[...]}

References: BS 1192-4:2014, USACE EM 1110-1-1000.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string"
    },
    "submodels": {
      "type": "array",
      "description": "List of discipline submodel dicts",
      "items": {
        "type": "object",
        "properties": {
          "discipline": {
            "type": "string"
          },
          "coordinate_system": {
            "type": "string"
          },
          "datum_elevation": {
            "type": "number"
          },
          "elements": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "id": {
                  "type": "string"
                },
                "bbox": {
                  "type": "array"
                }
              }
            }
          }
        },
        "required": [
          "discipline",
          "elements"
        ]
      }
    }
  },
  "required": [
    "submodels"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
