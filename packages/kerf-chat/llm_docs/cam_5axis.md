# 5-axis CAM — G-code emission (constant-tilt + 3+2 indexed)

Kerf generates real 5-axis G-code via two modes:

- **Constant-tilt** (T5): each CL point carries a tool-axis vector `(i,j,k)`;
  A/B rotary angles are emitted on every `G1` line.
- **3+2 indexed** (T6): the table is positioned once at the top of the program
  (`G0 A<a> B<b>`), then a pure 3-axis body runs with A/B held constant.

Both modes use the same `POST /run-5axis` endpoint and the same LinuxCNC / Fanuc
post-processors.

The pipeline has two entry points:

1. **`POST /run-cam`** with `operation="5axis_finish"` or `operation="3plus2"` —
   accepts a STEP file, dispatches to the CL pipeline, then emits G-code.
   _Currently requires precomputed CL points; see note below._

2. **`POST /run-5axis`** — accepts precomputed CL points directly.  Fastest
   path for scripting workflows where the CL data is already available.
   Use `mode="constant_tilt"` (default) or `mode="3plus2"`.

## LLM tool — `cam_run` with `operation="5axis_finish"`

```
file_id           UUID of the STEP file (required)
operation         "5axis_finish" (or alias "5axis")
drive_face_id     Zero-based OCC face index of the drive surface (required)
tilt_deg          Tool-axis tilt off surface normal in degrees [0–30] (default 15)
lead_deg          Lead/lag tilt along path direction (optional, default 0)
tool_diameter     Ball-end mill diameter in mm (default 3.0)
step_over         ISO-curve row spacing in mm (default 0.5)
step_down         Depth-of-cut (passed to T3; typically 0 for finishing)
feed_rate         Cutting feed rate in mm/min (default 1000.0)
spindle_speed     Spindle speed in RPM (default 12000)
kinematic_family  "head_table" (A-around-X, B-around-Y) — only supported value
post_processor_5x "linuxcnc" (default) | "fanuc"
use_tcp           Emit G43.4 TCP mode (default false)
```

### Example — constant-tilt finishing

```json
{
  "file_id": "<uuid>",
  "operation": "5axis_finish",
  "drive_face_id": 2,
  "tilt_deg": 15.0,
  "tool_diameter": 4.0,
  "step_over": 1.0,
  "feed_rate": 800.0,
  "spindle_speed": 18000,
  "post_processor_5x": "linuxcnc"
}
```

## REST endpoint — `POST /run-5axis`

Accepts precomputed CL points (from `run_constant_tilt` or `run_3_2_indexed`)
and emits G-code without needing a STEP file.

### Constant-tilt mode (default)

Body:

```json
{
  "cl_points": [
    {"x": 0.0, "y": 0.0, "z": 2.5, "i": 0.259, "j": 0.0, "k": 0.966},
    {"x": 5.0, "y": 0.0, "z": 2.5, "i": 0.259, "j": 0.0, "k": 0.966},
    {"x": 10.0, "y": 0.0, "z": 2.5, "i": 0.259, "j": 0.0, "k": 0.966}
  ],
  "mode": "constant_tilt",
  "post": "linuxcnc",
  "tool_number": 1,
  "feed_rapid_mm_min": 5000,
  "feed_cut_mm_min": 800,
  "spindle_rpm": 18000,
  "use_tcp": false,
  "machine_kinematic": "head_table",
  "coolant": "flood"
}
```

### 3+2 indexed mode

Body — CL points are in the **rotated frame** (output of `run_3_2_indexed`).
The `i/j/k` on the first point encodes the drive-face tool-axis vector; all
points in the job share the same orientation:

```json
{
  "cl_points": [
    {"x": 0.0, "y": 0.0, "z": 0.5, "i": 0.354, "j": 0.354, "k": 0.707},
    {"x": 2.0, "y": 0.0, "z": 0.5, "i": 0.354, "j": 0.354, "k": 0.707},
    {"x": 4.0, "y": 0.0, "z": 0.5, "i": 0.354, "j": 0.354, "k": 0.707}
  ],
  "mode": "3plus2",
  "post": "linuxcnc",
  "feed_cut_mm_min": 800,
  "spindle_rpm": 18000,
  "coolant": "flood"
}
```

The emitter extracts A/B from the first point's i/j/k, emits one `G0 A<a> B<b>`
orientation move, then writes pure X/Y/Z `G1` lines for the body.

Response (both modes):

```json
{
  "output_key": "gcode",
  "gcode_b64": "<base64 G-code>",
  "cl_point_count": 3,
  "post_processor": "linuxcnc",
  "mode": "3plus2",
  "warnings": [],
  "errors": []
}
```

## CL point schema

Each element of `cl_points` is an object with:

| Key | Type | Description |
|-----|------|-------------|
| `x` | float | Tool-tip X position (mm) |
| `y` | float | Tool-tip Y position (mm) |
| `z` | float | Tool-tip Z position (mm) |
| `i` | float | Tool-axis unit vector X component |
| `j` | float | Tool-axis unit vector Y component |
| `k` | float | Tool-axis unit vector Z component |
| `feed` | float | (optional) Per-point feed override in mm/min |

`i`, `j`, `k` should form a unit vector.  The emitter normalises implicitly
via `atan2`.

In **3+2 indexed mode** the `i/j/k` encodes the drive-face orientation and only
needs to be present on the first CL point.  All body points use the same
rotation; subsequent `i/j/k` values are ignored.

## 3+2 indexed mode

### When to use 3+2 vs continuous-5-axis

| | 3+2 indexed | Continuous 5-axis |
|---|---|---|
| **Best for** | Pockets, faces, contours on angled faces; parts that can be fully machined from one tilted orientation | Sculptured surfaces, freeform shapes, impeller hubs |
| **G-code shape** | One `G0 A<a> B<b>` at top; plain `G1 X Y Z` body | Per-line `G1 X Y Z A<a> B<b>` |
| **Machine requirement** | Any 5-axis machine; no inverse-kinematics TCP required during cut | Requires live RTCP / G43.4 during cutting |
| **Cycle-time** | Lower (no rotary interpolation during cut) | Higher (constant rotary motion) |
| **Suitable controller** | All 5-axis controllers including older Fanuc 18i | Modern controllers (Fanuc 30i/31i, LinuxCNC ≥2.8) |

### Input: `target_face_normal`

`run_3_2_indexed` (T4) requires a `drive_face_normal` — the `[nx, ny, nz]`
outward normal of the face you want to mill normal-to.  T4 builds a rotation R
that maps this normal to `+Z`, rotates all STL triangles, runs the chosen
3-axis sub-op on the rotated geometry, and returns:

```json
{
  "cl_points": [{"x": ..., "y": ..., "z": ...}, ...],
  "rotation_matrix": [[r00, r01, r02], ...],
  "rotated_normal": [0.0, 0.0, 1.0],
  "warnings": [...]
}
```

The `cl_points` are in the rotated frame.  Pass them to
`emit_gcode_indexed_3_2` with the first point carrying the `i/j/k` tool-axis
vector that encodes the drive-face orientation.

Convenience: `run_3_2_indexed` does not add `i/j/k` to the returned
`cl_points` — you need to compute the (i, j, k) corresponding to `drive_face_normal`
and add it to the first point, or pass the original `drive_face_normal` as the
tool-axis vector directly.  The T6 emitter only reads `i/j/k` from the first
point.

### Sample output — LinuxCNC, A=30°, B=45°, 5 XY points

```gcode
%
; INFO: drive face is axis-aligned ...   ← only if axis-aligned
; WARNING: no collision/gouge check ...
; Generated by Kerf CAM — LinuxCNC 3+2 indexed post (head_table A/B)
; Machine kinematic: head_table
; TCP mode: tool-tip coords (machine handles RTCP)
; Indexed orientation: A=30.000 B=45.000
G90 G94 G17 G21
G54
M6 T1
G0 Z50.000 A0.000 B0.000
; G43.4 H1  ; uncomment to enable TCP if machine supports it
G0 A30.000 B45.000 F5000     ← ONE orientation move
S12000 M3
M8
G0 X0.000 Y0.000 Z2.500 F5000
G1 X0.000 Y0.000 Z0.500 F1000
G1 X2.000 Y0.000 Z0.500      ← pure X/Y/Z, no A/B
G1 X4.000 Y0.000 Z0.500
G1 X6.000 Y0.000 Z0.500
G1 X8.000 Y0.000 Z0.500
G0 Z50.000 F5000
G0 A0.000 B0.000             ← return rotaries to home
G49
M9
M5
M30
%
```

### Axis-aligned short-circuit (A=B=0)

When `drive_face_normal ≈ (0,0,1)` (face already normal to +Z), T6 detects
`A=0, B=0` and skips the orientation move entirely.  The output is plain 3-axis
G-code with an informational comment.  The footer still emits `G0 A0.000 B0.000`
(harmless no-op on a machine where the rotaries are already at home).

### End-of-program: home rotation decision

The footer always returns the rotaries to home (`G0 A0.000 B0.000`) regardless
of whether the job was axis-aligned.  Rationale: leaving the table parked at a
non-zero orientation after the program ends is a safety hazard — the next
program (typically a 3-axis op) would machine at the skewed angle.  Operators
who want to leave the table indexed can comment out the `G0 A0.000 B0.000` footer
line manually.

## Angle conventions — head_table kinematic

The only supported machine kinematic is `head_table` (A rotates around X,
B rotates around Y — the most common 5-axis VMC / router layout):

```
B = atan2(sqrt(i² + j²), k)   — polar angle off +Z (tilt / inclination)
                                  B=0° when tool is vertical (+Z)
A = atan2(j, i)               — azimuth around +Z (in-plane rotation)
                                  A=0° when tool tilts in the +X direction
                                  A=90° when tool tilts in the +Y direction
```

### Machine kinematic options

| Value | Description | Status |
|-------|-------------|--------|
| `head_table` | A-around-X, B-around-Y (default) | Supported |
| `table_table` | Both rotaries on table (trunnion) | Planned v0.3 |
| `head_head` | Both rotaries on spindle (A+C variant) | Planned v0.3 |

## Post-processor options

### LinuxCNC (`linuxcnc`)

- Feed mode: **G94** (feed-per-minute).  G93 inverse-time is not emitted —
  see note below.
- Tape markers: `%` at start and end.
- TCP: `G43.4 H<n>` when `use_tcp=true`; commented-out hint when false.
- Coolant: `M8` (flood) / `M7` (mist) / none.
- Singularity warning: emitted as a `;` comment when B≈0 is detected.

### Fanuc (`fanuc`)

- N-line numbers: `N10`, `N20`, … per line.  Disabled by `no_n_numbers=true`.
- Comments: Fanuc `(...)` parenthetical style.
- TCP + AICC: `G43.4 H<n>` + `G05.1 Q1`/`G05.1 Q0` when `use_tcp=true`.
  Commented-out hint when false.
- Suitable for Fanuc Series 30i/31i.  Series 18i and earlier: set `use_tcp=false`
  and configure RTCP via the machine parameter table.

### G93 (inverse-time feed) — why not shipped

G93 requires computing `F = 60 / move_duration_seconds` per line.  The duration
depends on both linear travel and angular travel, which varies with kinematic
family.  LinuxCNC's trajectory planner enforces joint velocity/acceleration
limits automatically in G94 mode (since v2.8), making G93 unnecessary for
small VMC / hobbyist 5-axis machines.  G93 is deferred to a post-v0.2 row.

## Continuous A-angle unwrap

A consecutive A jump of more than ±180° is unwrapped: the emitter tracks the
previous A and folds each new raw A into the nearest equivalent.  This prevents
the machine from taking a 340° rotary slew when a 20° move was intended.

Near-singularity handling: when `k ≥ cos(1°)` (tool nearly vertical, B≈0),
A is ill-defined.  The previous A is held instead, and a warning comment is
emitted in the G-code.

## Known limitations

- **No collision / gouge check** — verify the toolpath with CAMotics before
  sending to a machine.  A warning is always emitted in the G-code header.
- **head_table only** — other kinematic families (table_table, head_head A-C)
  require different inverse-kinematics math and are deferred to v0.3.
- **No pivot-offset TCP math** — the emitter outputs tool-tip coordinates
  directly.  TCP coordinate transformation (accounting for the A/B pivot-to-
  spindle distance) is the machine controller's responsibility (G43.4 RTCP).
  If your machine does not support RTCP, you must compute machine joint
  coordinates externally and set `use_tcp=false`.
- **G93 inverse-time not supported** — G94 feed-per-minute only.

## Python API

### Constant-tilt

```python
from kerf_cam.five_axis.gcode_constant_tilt import emit_gcode_constant_tilt, PostOpts

cl_points = [
    {"x": 0.0, "y": 0.0, "z": 2.5, "i": 0.259, "j": 0.0, "k": 0.966},
    {"x": 5.0, "y": 0.0, "z": 2.5, "i": 0.259, "j": 0.0, "k": 0.966},
]

opts = PostOpts(
    tool_number=1,
    feed_rapid_mm_min=5000.0,
    feed_cut_mm_min=800.0,
    spindle_rpm=18000,
    use_tcp=False,
    machine_kinematic="head_table",
    coolant="flood",
)

gcode = emit_gcode_constant_tilt(cl_points, post="linuxcnc", opts=opts)
print(gcode)
```

### 3+2 indexed

```python
from kerf_cam.five_axis.gcode_indexed_3_2 import emit_gcode_indexed_3_2
from kerf_cam.five_axis.gcode_constant_tilt import PostOpts

# CL points from run_3_2_indexed (rotated frame).
# Add i/j/k to first point encoding the drive-face tool-axis direction.
import math
a_deg, b_deg = 30.0, 45.0
b_rad, a_rad = math.radians(b_deg), math.radians(a_deg)
tool_axis = (math.sin(b_rad)*math.cos(a_rad),
             math.sin(b_rad)*math.sin(a_rad),
             math.cos(b_rad))

cl_points = [
    {"x": 0.0, "y": 0.0, "z": 0.5,
     "i": tool_axis[0], "j": tool_axis[1], "k": tool_axis[2]},
    {"x": 2.0, "y": 0.0, "z": 0.5},
    {"x": 4.0, "y": 0.0, "z": 0.5},
]

opts = PostOpts(feed_cut_mm_min=800.0, spindle_rpm=18000)
gcode = emit_gcode_indexed_3_2(cl_points, post="linuxcnc", opts=opts)
print(gcode)
```

## Full pipeline example (Python scripting)

```python
from kerf_cam.five_axis.constant_tilt import run_constant_tilt
from kerf_cam.five_axis.gcode_constant_tilt import emit_gcode_constant_tilt, PostOpts

# 1. Generate CL points from a STEP file
result = run_constant_tilt({
    "brep_path": "/path/to/part.step",
    "drive_face_id": 2,
    "tilt_deg": 15.0,
    "step_over_mm": 1.0,
    "ball_radius_mm": 2.0,
})

if result.get("errors"):
    raise RuntimeError(result["errors"])

# 2. Emit G-code
opts = PostOpts(feed_cut_mm_min=800.0, spindle_rpm=18000)
gcode = emit_gcode_constant_tilt(result["cl_points"], post="fanuc", opts=opts)

with open("toolpath.nc", "w") as f:
    f.write(gcode)
```
