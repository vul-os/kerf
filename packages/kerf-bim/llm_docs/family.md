# family

*Module: `kerf_bim.tools.family` · Domain: bim*

This module registers **7** LLM tool(s):

- [`create_family`](#create-family)
- [`add_family_param`](#add-family-param)
- [`add_family_type`](#add-family-type)
- [`instantiate_family`](#instantiate-family)
- [`update_instance`](#update-instance)
- [`flex_family`](#flex-family)
- [`set_family_representation`](#set-family-representation)

---

## `create_family`

Create a new .family.json parametric component template. category must be one of: Wall, Floor, Roof, Door, Window, Column, Beam, Stair, Railing, Ceiling, Furniture, Generic. Each param needs at minimum {name, type}; number params accept min/max; enum params require an options list.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Absolute path, must end with .family.json"
    },
    "name": {
      "type": "string"
    },
    "category": {
      "type": "string"
    },
    "params": {
      "type": "array",
      "items": {
        "type": "object",
        "properties": {
          "name": {
            "type": "string"
          },
          "type": {
            "type": "string"
          },
          "unit": {
            "type": "string"
          },
          "default": {},
          "options": {
            "type": "array"
          },
          "min": {
            "type": "number"
          },
          "max": {
            "type": "number"
          }
        },
        "required": [
          "name",
          "type"
        ]
      }
    }
  },
  "required": [
    "path",
    "name",
    "category"
  ]
}
```

---

## `add_family_param`

Add a parameter definition to an existing .family.json file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "type": {
      "type": "string"
    },
    "unit": {
      "type": "string"
    },
    "default": {},
    "options": {
      "type": "array"
    },
    "min": {
      "type": "number"
    },
    "max": {
      "type": "number"
    }
  },
  "required": [
    "file_id",
    "name",
    "type"
  ]
}
```

---

## `add_family_type`

Add a named parameter preset (type) to a .family.json file. A type is a saved set of param values; instances can reference it via type_id.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string"
    },
    "id": {
      "type": "string",
      "description": "Unique id for this type, e.g. 'type-600x900'"
    },
    "name": {
      "type": "string"
    },
    "params": {
      "type": "object"
    }
  },
  "required": [
    "file_id",
    "id",
    "name"
  ]
}
```

---

## `instantiate_family`

Append an instance record to a .bim file. The instance references a family by its file_id and optionally a type_id and per-instance param overrides.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "family_file_id": {
      "type": "string"
    },
    "host_file_id": {
      "type": "string",
      "description": "UUID of the .bim file"
    },
    "host_ref": {
      "type": "string",
      "description": "e.g. wall element id"
    },
    "type_id": {
      "type": "string"
    },
    "params": {
      "type": "object"
    }
  },
  "required": [
    "family_file_id",
    "host_file_id"
  ]
}
```

---

## `update_instance`

Update per-instance param overrides for an existing family instance in a .bim file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "host_file_id": {
      "type": "string"
    },
    "instance_id": {
      "type": "string"
    },
    "params": {
      "type": "object"
    }
  },
  "required": [
    "host_file_id",
    "instance_id",
    "params"
  ]
}
```

---

## `flex_family`

Exercise a .family.json definition across multiple parameter sets and return the resolved values for each set. Useful as a 'flex panel' to verify that the family produces correct resolved parameters across its full range. Each item in 'parameter_sets' is an instance dict ({type_id?, params?}) resolved against the family; results are returned in the same order.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the .family.json file to flex"
    },
    "parameter_sets": {
      "type": "array",
      "description": "List of instance dicts to resolve. Each item: {type_id?, params?}.",
      "items": {
        "type": "object"
      },
      "minItems": 1
    }
  },
  "required": [
    "file_id",
    "parameter_sets"
  ]
}
```

---

## `set_family_representation`

Attach a geometry representation hint to a .family.json file. This links the parametric parameter schema to a geometry source so renderers and exporters know how to produce geometry from resolved parameter values. kind must be one of: geometry_ref, feature_tree, circuit_ref, parametric_box.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the .family.json file"
    },
    "kind": {
      "type": "string",
      "description": "Representation kind (geometry_ref | feature_tree | circuit_ref | parametric_box)"
    },
    "ref": {
      "type": "string",
      "description": "For geometry_ref/feature_tree: file path or id of the geometry. For parametric_box: omit."
    },
    "size_params": {
      "type": "object",
      "description": "For parametric_box: mapping of box dimension to param name, e.g. {\"x\": \"width\", \"y\": \"depth\", \"z\": \"height\"}."
    }
  },
  "required": [
    "file_id",
    "kind"
  ]
}
```

---

## See also

- Package: `kerf_bim`
