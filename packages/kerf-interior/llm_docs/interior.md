# kerf-interior — Space Planning, FF&E & ADA Clearances

`kerf-interior` is the Kerf plugin for architectural interior design, space
planning, furniture/fixture/equipment (FF&E) layout, and accessibility
compliance checking (ADA 2010 / ANSI A117.1-2009).

---

## Tools

### `interior_clearance_check`

Run ADA / ANSI A117.1 dimensional clearance checks against supplied
measurements.  Returns a list of violations (empty = fully compliant).

**Key limits built-in**

| Check | Limit | Reference |
|-------|-------|-----------|
| Wheelchair turning circle | 1524 mm (60 in) diameter | ADA §304.3.1 |
| Minimum corridor width | 914 mm (36 in) | ADA §403.5.1 |
| Max forward reach (high) | 1219 mm (48 in) | ADA §308.2.1 |
| Min forward reach (low) | 381 mm (15 in) | ADA §308.2.1 |
| Knee clearance height | 686 mm (27 in) | ADA §306.3.1 |
| Knee clearance depth | 483 mm (19 in) | ADA §306.3.3 |

**Example call**

```json
{
  "turning_diameter_mm": 1524,
  "corridor_widths_mm": [1200, 900],
  "knee_clearances": [{"height_mm": 686, "depth_mm": 483}],
  "reach_heights_mm": [1100, 400]
}
```

**Example response (compliant)**

```json
{"compliant": true, "violation_count": 0, "violations": []}
```

**Example response (violation)**

```json
{
  "compliant": false,
  "violation_count": 1,
  "violations": [
    {
      "rule": "corridor_width",
      "actual_mm": 800.0,
      "limit_mm": 914.0,
      "message": "Corridor width 800.0 mm is less than ADA minimum 914 mm (36 in). Deficit: 114.0 mm."
    }
  ]
}
```

---

### `interior_make_furniture`

Generate a parametric FF&E item.  Returns a JSON object with bounding-box
dimensions, clearance zones, and metadata.

**`kind` values**: `"chair"`, `"desk"`, `"sofa"`, `"table"`

**Example — accessible task desk**

```json
{
  "kind": "desk",
  "name": "Accessible Work Desk",
  "width_mm": 1500,
  "depth_mm": 750,
  "height_mm": 730,
  "with_ada_clearance": true
}
```

**Response shape**

```json
{
  "name": "Accessible Work Desk",
  "kind": "desk",
  "width_mm": 1500,
  "depth_mm": 750,
  "height_mm": 730,
  "seat_height_mm": null,
  "clearance_front_mm": 914,
  "clearance_back_mm": 100,
  "clearance_left_mm": 50,
  "clearance_right_mm": 50,
  "origin": null,
  "rotation_deg": 0,
  "metadata": {
    "knee_clearance_height_mm": 686,
    "knee_clearance_depth_mm": 483
  }
}
```

---

### `interior_room_layout`

Create a room, optionally declare circulation paths, and run a full ADA audit.

**Example**

```json
{
  "name": "Open Office",
  "width_mm": 12000,
  "depth_mm": 8000,
  "ceiling_height_mm": 2700,
  "circulation_paths": [
    {
      "name": "Main aisle",
      "start": [0, 4000],
      "end": [12000, 4000],
      "clear_width_mm": 1500
    }
  ],
  "turning_diameter_mm": 1524,
  "reach_heights_mm": [900, 1100]
}
```

**Response**

```json
{
  "name": "Open Office",
  "width_mm": 12000,
  "depth_mm": 8000,
  "ceiling_height_mm": 2700,
  "area_m2": 96.0,
  "item_count": 0,
  "circulation_path_count": 1,
  "ada_violations": 0,
  "violations": []
}
```

---

## Python API

```python
from kerf_interior.clearance import (
    check_turning_radius,       # ADA §304.3.1 — 1524 mm turning circle
    check_corridor_clearance,   # ADA §403.5.1 — 914 mm min corridor
    check_knee_clearance,       # ADA §306.3   — 686 mm h × 483 mm d
    check_reach_range,          # ADA §308.2.1 — 381–1219 mm
    audit_clearances,           # batch helper
    turning_circle_diameter_mm, # returns 1524.0 (or 2 × radius)
)
from kerf_interior.furniture import make_chair, make_desk, make_sofa, make_table
from kerf_interior.space_planning import make_room
```

### Quick-start

```python
from kerf_interior.space_planning import make_room
from kerf_interior.furniture import make_desk, make_chair

# Create a 6 m × 5 m room
room = make_room("Home Office", 6000, 5000)

# Place furniture
desk = make_desk(name="Standing Desk", width_mm=1800)
room.place(desk, x_mm=500, y_mm=500)

chair = make_chair()
room.place(chair, x_mm=600, y_mm=1300)

# Add a circulation path
room.add_circulation_path("Exit aisle", (0, 2500), (6000, 2500), 1200)

# Run full ADA audit
violations = room.audit_all(
    turning_diameter_mm=1524,
    reach_heights_mm=[1100],
)
for v in violations:
    print(v.rule, v.message)
```

---

## ADA / ANSI Reference

All dimension constants are defined in `kerf_interior.clearance` and match:

- **ADA Standards for Accessible Design, 2010** (U.S. Department of Justice)
- **ANSI A117.1-2009**: Accessible and Usable Buildings and Facilities
- **ICC A117.1-2017** (updated reach-range tables)

### Turning space (§304.3.1)

A wheelchair turning space must provide either a 60-inch (1524 mm) diameter
circular clear floor area or a T-shaped turning space.  `check_turning_radius`
applies the circular criterion with an optional construction tolerance (default
5 mm).

### Corridor clear width (§403.5.1)

Walking surfaces must be at least 36 inches (914 mm) wide.  Passing spaces of
60 × 60 inches (1524 × 1524 mm) are required at intervals ≤ 200 feet in
corridors narrower than 60 inches.

### Reach ranges (§308)

| Direction | High | Low |
|-----------|------|-----|
| Forward (unobstructed) | 1219 mm (48 in) | 381 mm (15 in) |
| Side (unobstructed) | 1219 mm (48 in) | 381 mm (15 in) |

### Knee clearance (§306.3)

| Dimension | Minimum |
|-----------|---------|
| Height (underside of surface) | 686 mm (27 in) |
| Depth | 483 mm (19 in) |

---

## Capabilities declared

| Capability key | Description |
|----------------|-------------|
| `interior.ada-audit` | ADA / ANSI A117.1 dimensional checks |
| `interior.space-planning` | RoomLayout with circulation paths |
| `interior.ffe` | Parametric FF&E generators |
| `interior.clearance-check` | `interior_clearance_check` LLM tool |
| `interior.make-furniture` | `interior_make_furniture` LLM tool |
| `interior.room-layout` | `interior_room_layout` LLM tool |
