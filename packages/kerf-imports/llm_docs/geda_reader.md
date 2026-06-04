# import_geda

*Module: `kerf_imports.geda_reader` · Domain: imports*

## Description

Import a gEDA gschem schematic (.sch) or PCB layout (.pcb) file into the current Kerf project. Accepts a blob_id or storage_key pointing to the uploaded gEDA file. Parses component instances, net connectivity, and board routing into a structured netlist + footprint model. Gate: imports.geda capability.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "project_id": {
      "type": "string",
      "description": "UUID of the target Kerf project."
    },
    "file_blob_id_or_storage_key": {
      "type": "string",
      "description": "Blob ID or storage key for the gEDA .sch/.pcb file."
    },
    "import_folder": {
      "type": "string",
      "description": "Path in the project tree for the imported file. Defaults to /geda_import."
    }
  },
  "required": [
    "project_id",
    "file_blob_id_or_storage_key"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="import_geda",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
