# import_ibis

*Module: `kerf_imports.ibis_reader` · Domain: imports*

## Description

Import an IBIS (I/O Buffer Information Specification, ANSI/EIA-656) signal-integrity model file into the current project. Accepts a blob_id or storage_key pointing to the uploaded .ibs file. Parses component/pin tables, buffer models (Output/Input/I/O/3-state), package parasitics (R/L/C), V-I tables, ramp data, and voltage/temperature ranges.  Returns a structured model with components, pins, and models. Gate: imports.ibis capability.

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
      "description": "Blob ID or storage key for the .ibs file."
    },
    "import_folder": {
      "type": "string",
      "description": "Path in the project tree for the imported file. Defaults to /ibis_import."
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
    tool_name="import_ibis",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
