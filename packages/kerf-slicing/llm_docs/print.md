# Print (.print) — 3D-print slicing configuration file format

A `.print` file is a JSON document that references a target mesh and a dict of
FDM slicing settings. It is compiled to G-code via the `run_print_slice` LLM
tool or the `POST /run-print-slice` pyworker route (backed by CuraEngine).

## LLM tool

```
run_print_slice(target_mesh_ref: str, settings?: PrintSettings)
  → { layer_count, print_time_s, filament_mm, gcode_preview, gcode_bytes, warnings }
```

- `target_mesh_ref` — absolute project path to the source STL
  (e.g. `/models/bracket.stl`).
- `settings` — optional dict of print settings (see below).

## .print file schema

```json
{
  "version": 1,
  "mesh_ref": "/models/bracket.stl",
  "settings": {
    "layer_height": 0.2,
    "infill_density": 20,
    "perimeters": 3,
    "retraction_enabled": true,
    "print_temperature": 200,
    "bed_temperature": 60
  }
}
```

## Settings reference

| Key                  | Type    | Default | CuraEngine key               | Description                             |
|----------------------|---------|---------|------------------------------|-----------------------------------------|
| `layer_height`       | number  | 0.2     | `layer_height`               | Layer height in mm (0.05 – 0.35)       |
| `infill_density`     | number  | 20      | `infill_sparse_density`      | Infill density in % (0 – 100)          |
| `perimeters`         | integer | 3       | `wall_line_count`            | Number of perimeter walls (1 – 10)     |
| `retraction_enabled` | boolean | true    | `retraction_enable`          | Enable retraction to reduce stringing  |
| `print_temperature`  | number  | 200     | `material_print_temperature` | Nozzle temperature in °C (150 – 300)   |
| `bed_temperature`    | number  | 60      | `material_bed_temperature`   | Bed temperature in °C (0 – 120)        |

Unknown keys are passed through directly to CuraEngine as `-s <key>=<value>`,
allowing advanced overrides not yet modelled in the Tier 1 schema.

## Error: CuraEngine not installed

When CuraEngine is not on the server PATH the tool returns:

```json
{
  "error": "CURA_NOT_INSTALLED",
  "message": "CuraEngine not found on the server. Install it and ensure it is on PATH."
}
```

Prompt the user to install CuraEngine and try again. The tool does not fall
back silently — slicing requires the external binary.

## Tier 2 deferrals

The following settings are **not** implemented in Tier 1:

- Support structures (type, overhang angle, interface layers)
- Ironing (top surface smoothing)
- Adaptive layer heights
- Brim / raft / skirt
- Multiple extruders / multi-material

These will be added in a follow-up Tier 2 slice.
