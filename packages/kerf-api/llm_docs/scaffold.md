# scaffold

*Module: `kerf_api.tools.scaffold` · Domain: api*

This module registers **7** LLM tool(s):

- [`create_sketch`](#create-sketch)
- [`create_feature`](#create-feature)
- [`create_part`](#create-part)
- [`create_circuit`](#create-circuit)
- [`add_probe`](#add-probe)
- [`remove_probe`](#remove-probe)
- [`rename_probe`](#rename-probe)

---

## `create_sketch`

Create a new parametric 2D sketch file. The user authors geometry + dimensional/geometric constraints in the sketch UI; LLM tools cannot mutate sketches beyond creation. Sketches compile to a JSCAD Geom2 and can be imported by `.jscad` files via `import profile from '/path.sketch'`.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "plane": {
      "type": "string",
      "enum": [
        "XY",
        "XZ",
        "YZ"
      ]
    },
    "name": {
      "type": "string"
    },
    "description": {
      "type": "string"
    }
  },
  "required": [
    "path"
  ]
}
```

---

## `create_feature`

Create a new empty .feature file (OCCT B-rep timeline). After creation, append operations by editing the JSON via write_file / edit_file. Consult docs/llm/feature.md for the node-type vocabulary (pad / pocket / revolve / fillet / chamfer / shell / hole). Refuses .sketch / .assembly / .drawing / .part paths.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "name": {
      "type": "string"
    }
  },
  "required": [
    "path"
  ]
}
```

---

## `create_part`

Create a new Part file (kind='part') in the library. The Part stores manufacturer/MPN/distributor metadata as JSON; assemblies reference parts as Components and the BOM endpoint rolls them up. `name` is required; everything else can be filled in later by editing the file via write_file / edit_file.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "metadata": {
      "type": "object"
    }
  },
  "required": [
    "path",
    "metadata"
  ]
}
```

---

## `create_circuit`

Create a new tscircuit electronics-design file (`.circuit.tsx`). The user authors components + traces in JSX; the editor compiles to schematic, PCB, and 3D views via tscircuit.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "width_mm": {
      "type": "number"
    },
    "height_mm": {
      "type": "number"
    }
  },
  "required": [
    "path"
  ]
}
```

---

## `add_probe`

Add a SPICE simulation probe to a `.circuit.tsx` file. The probe references a schematic port (V) or component (I) and becomes a `.print` directive in the generated SPICE netlist.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_file_id": {
      "type": "string"
    },
    "name": {
      "type": "string"
    },
    "kind": {
      "type": "string",
      "enum": [
        "V",
        "I"
      ]
    },
    "target_id": {
      "type": "string"
    }
  },
  "required": [
    "circuit_file_id",
    "name",
    "kind",
    "target_id"
  ]
}
```

---

## `remove_probe`

Remove a SPICE simulation probe from a `.circuit.tsx` file by name. The matching `// @kerf-probe NAME=<name> ...` comment line is deleted. Tolerant: succeeds without error if no such probe exists.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_file_id": {
      "type": "string"
    },
    "name": {
      "type": "string"
    }
  },
  "required": [
    "circuit_file_id",
    "name"
  ]
}
```

---

## `rename_probe`

Rename a SPICE simulation probe in a `.circuit.tsx` file. Rewrites the NAME field of the matching `// @kerf-probe` line, leaving KIND/PORT untouched. Tolerant: succeeds without error if no such probe exists.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "circuit_file_id": {
      "type": "string"
    },
    "old_name": {
      "type": "string"
    },
    "new_name": {
      "type": "string"
    }
  },
  "required": [
    "circuit_file_id",
    "old_name",
    "new_name"
  ]
}
```

---

## See also

- Package: `kerf_api`
