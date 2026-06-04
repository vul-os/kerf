# extrude_sketch_to_jscad

*Module: `kerf_cad_core.extrude_sketch_to_jscad` · Domain: cad*

## Description

Scaffold a new .jscad file that imports a .sketch profile and applies an extrusion to produce a 3D part. The sketch remains the source of truth — editing its dimensions reflows the 3D. Supported ops: 'extrude_linear' (linear pad), 'extrude_rotate' (revolve around the sketch's vertical axis), 'sweep_along_path' (sweep the profile along a second sketch's open path). Returns an error if target_path already exists (collision). For boolean ops (boss/cut), compose two extrudes via edit_file after scaffolding. For real B-rep + STEP export, use create_feature + feature_pad instead — see docs/llm/feature.md.

## Input schema

```json
{
  "type": "object",
  "properties": {
    "path": {
      "type": "string",
      "description": "Absolute path for the new .jscad file."
    },
    "sketch_file_id": {
      "type": "string",
      "description": "Absolute path to the .sketch profile, e.g. '/parts/bracket-outline.sketch'."
    },
    "operation": {
      "type": "string",
      "enum": [
        "extrude_linear",
        "extrude_rotate",
        "sweep_along_path"
      ],
      "description": "Which JSCAD extrusion op to apply."
    },
    "params": {
      "type": "object",
      "description": "Op-specific parameters. extrude_linear: {height_mm: number} or {height_param: string}. extrude_rotate: {angle_deg: number, segments?: integer}. sweep_along_path: {path_sketch_file_id: string}."
    },
    "object_id": {
      "type": "string",
      "description": "Id of the produced JSCAD Object; defaults to the sketch's basename (e.g. 'bracket' from 'bracket.sketch')."
    }
  },
  "required": [
    "path",
    "sketch_file_id",
    "operation",
    "params"
  ]
}
```

## Example call

```python
import json
# Invoke via the kerf chat tool runner.
result = json.loads(await tool_runner.run(
    tool_name="extrude_sketch_to_jscad",
    args={
        # fill required fields — see Input schema above
    }
))
```

## See also

- Package: `kerf_cad_core`
