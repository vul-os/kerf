# import_pads

*Module: `kerf_imports.pads_reader` · Domain: imports*

## Description

Import a PADS ASCII netlist or PCB layout file into the current Kerf project. Accepts a blob_id or storage_key pointing to the uploaded PADS file. Parses *PART*, *NET*, and *ROUTE* sections into structured parts, nets, signals, and footprints. Gate: imports.pads capability.

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
      "description": "Blob ID or storage key for the PADS ASCII file."
    },
    "import_folder": {
      "type": "string",
      "description": "Path in the project tree for the imported file. Defaults to /pads_import."
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
    tool_name="import_pads",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
