# import_qif

*Module: `kerf_imports.qif_reader` · Domain: imports*

## Description

Import a QIF 3.0 (Quality Information Framework, ISO 23952) inspection report into the current project. Accepts a blob_id or storage_key pointing to the uploaded .qif XML file. Parses characteristics (dimension/GD&T) with nominal, tolerance, actual values, and pass/fail status. Returns a structured inspection model with per-characteristic results and a summary pass/fail count. Gate: imports.qif capability.

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
      "description": "Blob ID or storage key for the .qif XML file."
    },
    "import_folder": {
      "type": "string",
      "description": "Path in the project tree for the imported file. Defaults to /qif_import."
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
    tool_name="import_qif",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
