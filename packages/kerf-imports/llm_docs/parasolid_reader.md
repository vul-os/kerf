# import_xt

*Module: `kerf_imports.parasolid_reader` · Domain: imports*

## Description

Parse a Parasolid X_T (text-transmit) ASCII file stored as a text/plain file in the project. Returns the assembly/body tree, topology counts (faces/edges/vertices), analytic surface and curve parameters, and a flat inventory ready for AFR/heal consumption. Unsupported record types are skipped with warnings.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "UUID of the X_T file stored as kind=step or text."
    }
  },
  "required": [
    "file_id"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="import_xt",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_imports`
