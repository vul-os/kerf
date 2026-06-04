# import_allegro

*Module: `kerf_imports.allegro_reader` · Domain: imports*

## Description

Import a Cadence Allegro PCB design file into the current Kerf project. Accepts a blob_id or storage_key pointing to an IPC-2581 XML export (preferred) or an Allegro ASCII netlist/board report. Parses components, nets, placement, and routing into a structured netlist + footprint model. Gate: imports.allegro capability.

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
      "description": "Blob ID or storage key for the Allegro IPC-2581 or ASCII file."
    },
    "import_folder": {
      "type": "string",
      "description": "Path in the project tree for the imported file. Defaults to /allegro_import."
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
    tool_name="import_allegro",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
