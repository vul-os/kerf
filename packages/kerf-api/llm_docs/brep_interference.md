# brep_interference

*Module: `kerf_api.tools.brep_interference` · Domain: api*

This module registers **2** LLM tool(s):

- [`brep_interference_volume`](#brep-interference-volume)
- [`brep_assembly_interference_matrix`](#brep-assembly-interference-matrix)

---

## `brep_interference_volume`

Compute the exact volume of intersection (interference) between two solid B-rep bodies in a CAD file. Returns the intersection volume, a normalised interference severity score (0=no overlap, 1=fully inside), the computation method, and statistical error. Use this to quantify collision severity and rank interference issues in assembly clearance analysis.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the CAD file containing the geometry."
    },
    "object_id_a": {
      "type": "string",
      "description": "ID of the first solid body (component A)."
    },
    "object_id_b": {
      "type": "string",
      "description": "ID of the second solid body (component B)."
    },
    "method": {
      "type": "string",
      "enum": [
        "boolean",
        "monte_carlo",
        "voxel"
      ],
      "description": "Computation method: 'boolean' (exact, fastest for simple analytic bodies), 'monte_carlo' (statistical, accurate for any shape, default), 'voxel' (discretised grid). Default: 'boolean'."
    },
    "n_samples": {
      "type": "integer",
      "description": "Number of MC samples (monte_carlo only). Default 10000."
    },
    "max_acceptable_volume": {
      "type": "number",
      "description": "Optional design threshold. If given, the result will include 'acceptable': true/false."
    }
  },
  "required": [
    "file_id",
    "object_id_a",
    "object_id_b"
  ]
}
```

---

## `brep_assembly_interference_matrix`

Compute the all-pairs interference volume matrix for an assembly file. Returns an N×N symmetric matrix where entry [i][j] is the interference volume between component i and component j, plus a ranked list of the most-severe pairs for prioritised design review. Use this for assembly clearance audits and collision severity ranking across all part pairs.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "assembly_file_id": {
      "type": "string",
      "description": "UUID of the assembly file."
    },
    "method": {
      "type": "string",
      "enum": [
        "boolean",
        "monte_carlo",
        "voxel"
      ],
      "description": "Computation method. Default: 'boolean'."
    },
    "n_samples": {
      "type": "integer",
      "description": "MC samples per pair (monte_carlo only). Default 5000."
    },
    "top_k": {
      "type": "integer",
      "description": "Number of worst-interference pairs to return in the ranked list. Default 10."
    }
  },
  "required": [
    "assembly_file_id"
  ]
}
```

---

## See also

- Package: `kerf_api`
