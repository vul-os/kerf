# CAM Layered Toolpath Generation

*Domain: CAM · Module: `packages/kerf-cad-core/src/kerf_cad_core/cam_layered.py` · Shipped: Wave 6*

## Overview

Generates 2.5D layered toolpaths (pocket clearing, contour finishing, drilling) from a 2-D sketch or BRep face boundary. Produces G-code for CNC mills and routers with configurable stepdown, stepover, climb/conventional milling, lead-in/out, and tool-change macros. Used as the primary toolpath generator for 2.5D prismatic parts; 3-D surface toolpaths are handled by the CAM wizard's parallel-finishing and waterline strategies.

## When to use

- Generating a pocket-clearing toolpath for a machined pocket from a sketch.
- Contouring the perimeter of a 2-D profile with finish allowance.
- Drilling a pattern of holes at specified depths and feed/speed conditions.

## API

```python
from kerf_cad_core.cam_layered import (
    LayeredCAMConfig, generate_pocket_toolpath,
    generate_contour_toolpath, toolpath_to_gcode,
)

config = LayeredCAMConfig(
    tool_diameter_mm=6.0,
    spindle_rpm=18000,
    feed_mm_min=1200,
    plunge_mm_min=400,
    stepdown_mm=2.0,
    stepover_frac=0.45,
    milling_direction="climb",
    finish_allowance_mm=0.1,
)

tp = generate_pocket_toolpath(
    boundary_polyline=[[0,0],[60,0],[60,40],[0,40],[0,0]],
    depth_mm=10.0,
    config=config,
)

gcode = toolpath_to_gcode(tp, machine="grbl")
```

## LLM tools

`cam_layered_pocket`, `cam_layered_contour`, `cam_layered_drill`

## References

- Smid, *CNC Programming Handbook*, 3rd ed. (2008).
- Nee et al., *Computer-Aided Process Planning* (1995).

## Honest caveats

Toolpaths are generated in 2.5D (constant Z layers). 3-D simultaneous 5-axis moves require the `cam_wizard` 3-D strategies. Lead-in/out geometry is a simple ramp or arc; sophisticated tool engagement control (adaptive clearing) is not implemented. Tool radius compensation (G41/G42) is applied at the G-code level using the configured tool diameter.
