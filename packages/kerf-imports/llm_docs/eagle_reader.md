# import_eagle

*Module: `kerf_imports.eagle_reader` · Domain: imports*

## Description

Import an Autodesk Eagle schematic (.sch) or board (.brd) XML file into the current Kerf project. Accepts a blob_id or storage_key pointing to the uploaded Eagle XML file. Parses parts/nets from schematics and elements/signals/footprints from board files.  Returns a structured netlist + footprint model. Gate: imports.eagle capability.

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
      "description": "Blob ID or storage key for the Eagle .sch/.brd file."
    },
    "import_folder": {
      "type": "string",
      "description": "Path in the project tree for the imported file. Defaults to /eagle_import."
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
    tool_name="import_eagle",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
