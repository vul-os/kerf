# kerf-slicing

3D-print G-code slicing plugin for Kerf.

Compiles `.print` JSON configuration files → FDM G-code via
`POST /run-print-slice`, invoking CuraEngine as a subprocess.

## Installation

```bash
pip install kerf-slicing             # plugin skeleton only (no CuraEngine)
# CuraEngine must be installed separately — it is NOT bundled.
# Ubuntu/Debian: apt-get install cura-engine
# macOS: brew install curaengine   (or build from source)
# https://github.com/Ultimaker/CuraEngine
```

## Licensing notice

`kerf-slicing` itself is MIT-licensed.

[CuraEngine](https://github.com/Ultimaker/CuraEngine) is **AGPLv3-licensed**.
This has the following practical implications:

- **Hosted service**: Kerf's cloud backend invokes CuraEngine as a **separate
  subprocess** via the `POST /run-print-slice` pyworker route. Subprocess
  execution is not considered "linking" under the AGPL, so the hosted service
  remains MIT-compatible. The subprocess boundary is the same technique used
  by kerf-wiring's WireViz integration.
- **Local / OSS install**: If you run the Kerf server locally and CuraEngine is
  on your PATH, it is invoked as a child process. The plugin itself never
  imports CuraEngine as a library, so the AGPL's copyleft obligations do not
  apply to the plugin code. You must of course comply with the CuraEngine AGPL
  licence with respect to CuraEngine itself (e.g. if you distribute a modified
  CuraEngine binary you must supply the modified source).
- **If you don't need 3D-print slicing**: simply don't install CuraEngine.
  The plugin loads cleanly; the `POST /run-print-slice` route returns a
  descriptive error instead of crashing:
  `CuraEngine not found. Install it and ensure it is on PATH.`

CuraEngine AGPLv3 notice: <https://github.com/Ultimaker/CuraEngine/blob/master/LICENSE>

## Tier 1 scope

This release ships the minimum shippable subset:

- CuraEngine subprocess wrapper with 60 s timeout
- Basic settings: `layer_height`, `infill_density`, `perimeters`,
  `retraction_enabled`, `print_temperature`, `bed_temperature`
- `.print` file kind (JSON config referencing a target mesh + settings dict)
- `run_print_slice` LLM tool + `POST /run-print-slice` pyworker route
- `PrintSliceView.jsx` with settings panel, layer count / time display,
  first-50-lines G-code preview, and a 2D layer scrubber (X-Y nozzle path)

## Tier 2 deferrals

- PrusaSlicer as an alternative slicer backend
- Advanced settings: supports tuning, ironing, adaptive layers, brim/raft
- Full G-code parser for accurate time/material estimation
- Per-layer thumbnail rendering
