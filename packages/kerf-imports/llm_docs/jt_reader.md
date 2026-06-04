# import_jt

*Module: `kerf_imports.jt_reader` · Domain: imports*

## Description

Import a Siemens JT file (v8–v10) into the current project. Accepts a blob_id or storage_key pointing to the uploaded .jt binary. Parses the assembly tree, tessellated meshes, and metadata properties. Creates Kerf files (one .mesh per JT part) under an import folder and returns the assembly tree, mesh statistics, and any warnings. XT B-rep segments are skipped with a warning (tessellation only). Gate: imports.jt capability.

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
      "description": "Blob ID or storage key for the .jt binary."
    },
    "import_folder": {
      "type": "string",
      "description": "Path in the project tree for imported files. Defaults to /jt_import."
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
    tool_name="import_jt",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
