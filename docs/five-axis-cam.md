# Five-Axis CAM

> Constant-tilt and 3+2 indexed five-axis surface-finishing toolpaths with Fanuc/LinuxCNC post-processing.

**Module**: `packages/kerf-cam/src/kerf_cam/five_axis/`
**Shipped**: Wave 8
**LLM tools**: `cam_run` (operation `5axis_constant_tilt`, `5axis_indexed_3_2`)

---

## What it is

Five-axis machining eliminates re-fixturing for complex sculptured surfaces and blisks. Kerf provides two five-axis strategies:

1. **Constant-tilt finishing** — the tool axis is tilted a fixed angle off the surface normal along the path tangent (Rodrigues rotation). Works on any drive face extracted from a STEP/BRep.
2. **3+2 indexed** — the machine tilts to a fixed orientation then cuts in 3-axis mode; good for features that have a clear preferred axis but cannot be reached at vertical.

Use constant-tilt for smooth organic surfaces, turbine blades, or die cavities. Use 3+2 indexed for undercut pockets and multi-face prismatic work.

## How to use it

### From chat

> "Generate a constant-tilt finishing toolpath on face 0 of my impeller.step with 8° tilt, 0.5 mm step-over, 4 mm ball-end mill."

### From Python

```python
from kerf_cam.five_axis.constant_tilt import run_constant_tilt

spec = {
    "brep_path": "impeller.step",
    "drive_face_id": 0,
    "tilt_deg": 8.0,
    "step_over_mm": 0.5,
    "ball_radius_mm": 2.0,
}
result = run_constant_tilt(spec)
print(len(result["cl_points"]), "CL points")
```

### From an LLM tool spec

```json
{"file_id": "<uuid>", "operation": "5axis_constant_tilt",
 "tool_id": "<ball-mill uuid>", "stepover": 0.5,
 "post": "fanuc"}
```

## How it works

For each UV iso-curve row at `step_over_mm` spacing, the algorithm: (1) queries surface normal **n** and U-tangent **t** at the sample point, (2) rotates **n** by `tilt_deg` about **t** using the Rodrigues formula, yielding the tool axis **a**, (3) offsets the ball centre by `radius × n` from the contact point, then computes the tip as `ball_centre − radius × a`. Optional lead/lag tilt is applied as a second rotation about `n × t`. The result is a CL data dict; G-code emission is handled by `posts/fanuc_5x.py` and `posts/linuxcnc_5x.py`.

## API reference

| Function | Returns | Purpose |
|---|---|---|
| `run_constant_tilt(spec)` | `dict` | Compute CL points for constant-tilt finishing |
| `run_indexed_3_2(spec)` | `dict` | Compute CL points for 3+2 indexed strategy |
| `fanuc_5x.emit(cl_points, config)` | `str` | Fanuc 5-axis G-code |
| `linuxcnc_5x.emit(cl_points, config)` | `str` | LinuxCNC 5-axis G-code |

## Example

```python
result = run_constant_tilt({
    "brep_path": "blade.step", "drive_face_id": 2,
    "tilt_deg": 5.0, "step_over_mm": 0.8, "ball_radius_mm": 3.0,
    "lead_deg": 2.0,
})
# result["cl_points"] = [{"x":…,"y":…,"z":…,"i":…,"j":…,"k":…}, …]
# result["warnings"] lists any degenerate UV regions skipped
```

## Honest caveats

Drive-face extraction uses OCCT via `kerf_cam.five_axis.drive_face`; this requires `pythonocc-core`. Without it, the plugin falls back to a flat-face mock. `tilt_deg` is validated to [0, 30]; values outside that range are rejected. No gouge avoidance is implemented — verify the toolpath visually before sending to the machine. Indexed 3+2 does not yet auto-select the optimal orientation.

## References

- Farouki, R.T. (1996). The Bernstein polynomial basis. *Comput. Aided Geom. Des.* 29(6), 379–419. (surface parametrisation)
- Bohez, E.L.J. (2002). Five-axis milling machine tool kinematic chain design and analysis. *Int. J. Mach. Tools Manuf.* 42(4), 505–520.
