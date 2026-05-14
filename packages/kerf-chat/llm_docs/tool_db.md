# Tool Database (`.tool` files)

A **tool** is a JSON file stored in the project with `kind = 'tool'`.  Each
tool has a stable `id` (e.g. `"T1"`) so CAM jobs can reference it rather than
hard-coding raw geometry parameters.

Tools are versionable per project and shareable via Workshop.

---

## Schema

```json
{
  "id": "T1",
  "name": "1/4\" carbide ball-end",
  "type": "ball_end",
  "diameter_mm": 6.35,
  "ball_radius_mm": 3.175,
  "flute_length_mm": 25,
  "shank_diameter_mm": 6.35,
  "overall_length_mm": 65,
  "flute_count": 2,
  "material": "carbide",
  "spindle_rpm_min": 8000,
  "spindle_rpm_max": 24000,
  "feed_rate_mm_min": 800,
  "plunge_rate_mm_min": 200,
  "notes": ""
}
```

### Required fields (all types)
| Field | Type | Notes |
|---|---|---|
| `id` | string | e.g. `"T1"` — must be unique in the project |
| `name` | string | Human-readable |
| `type` | string | See **Tool types** below |
| `diameter_mm` | number | Cutting diameter in mm |

### Extra required by type
| Type | Extra required field |
|---|---|
| `ball_end` | `ball_radius_mm` — must be ≤ `diameter_mm / 2` |
| `bull_end` | `corner_radius_mm` — must be ≤ `diameter_mm / 2` |
| `chamfer` | `included_angle_deg` — degrees, (0, 180) |
| `engraver` | `included_angle_deg` |
| `flat_end`, `drill`, `face_mill` | no extra required fields |

### Optional fields (all types)
`flute_length_mm`, `shank_diameter_mm`, `overall_length_mm`,
`tip_angle_deg` (drill, default 118°), `flute_count`, `material`,
`spindle_rpm_min`, `spindle_rpm_max`, `feed_rate_mm_min`,
`plunge_rate_mm_min`, `notes`.

---

## Tool types

| Type | Description |
|---|---|
| `ball_end` | Ball-nose end mill — use for 5-axis constant-tilt finishing |
| `flat_end` | Flat-bottom end mill — pocketing / profiling |
| `bull_end` | Torus / bull-nose — finishing with a small corner radius |
| `chamfer` | Chamfer cutter / V-bit |
| `drill` | Twist drill |
| `face_mill` | Face mill / fly-cutter |
| `engraver` | V-engraver / diamond drag |

---

## LLM tools

### `create_tool`
Create a new `.tool` file in the project.

```json
{
  "id": "T1",
  "name": "6mm carbide ball-end",
  "type": "ball_end",
  "diameter_mm": 6,
  "ball_radius_mm": 3,
  "flute_count": 2,
  "material": "carbide",
  "spindle_rpm_min": 10000,
  "feed_rate_mm_min": 800,
  "plunge_rate_mm_min": 200
}
```

Returns `{ file_id, tool_id, name, message }`.

### `update_tool`
Update an existing tool by `tool_id`. Only the supplied fields are changed;
others keep their existing values.

```json
{ "tool_id": "T1", "feed_rate_mm_min": 1000 }
```

### `delete_tool`
Soft-delete a tool by `tool_id`.

```json
{ "tool_id": "T1" }
```

### `list_tools`
List all tools in the project.  Returns `{ tools: [...], count: N }`.

---

## Using a tool in a CAM job

Pass `tool_id` in the `cam_run` spec instead of `ball_radius_mm`:

```json
{
  "file_id": "<step-file-id>",
  "operation": "5axis_finish",
  "tool_id": "T1",
  "drive_face_id": 5,
  "tilt_deg": 15
}
```

The post-processor automatically emits a comment line:

```
; tool: T1 — 6mm carbide ball-end, ø6 mm, ball r=3 mm, 2-flute, carbide
M6 T1
```

Feed rate and spindle RPM default to the tool's `feed_rate_mm_min` /
`spindle_rpm_min` when not explicitly set in the CAM job.

---

## Geometry sanity rules

- `ball_radius_mm` ≤ `diameter_mm / 2`
- `corner_radius_mm` ≤ `diameter_mm / 2`
- `included_angle_deg` ∈ (0°, 180°)
- `flute_length_mm` ≤ `overall_length_mm`
- `spindle_rpm_min` ≤ `spindle_rpm_max`
- All numeric fields must be positive
