# spaces_tools

*Module: `kerf_cad_core.arch.spaces_tools` · Domain: cad*

This module registers **3** LLM tool(s):

- [`arch_room`](#arch-room)
- [`arch_area_schedule`](#arch-area-schedule)
- [`arch_occupancy_load`](#arch-occupancy-load)

---

## `arch_room`

Compute the area, perimeter, occupancy load, and required egress width for a single room defined by its closed boundary polygon. All dimensions in millimetres; areas returned in both mm² and m². Occupancy load = ceil(net_area_m2 / IBC_factor). Egress width factors: nominal IBC § 1005.1 values (0.3 mm/person for stairways, 0.2 mm/person for other means). Load factors: nominal IBC Table 1004.5 values. Returns {ok: false, errors: [...]} for self-intersecting or degenerate polygons; never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "polygon": {
      "type": "array",
      "description": "Closed room boundary polygon as [[x1,y1],[x2,y2],...] in mm. Minimum 3 vertices. CW or CCW \u2014 both accepted.",
      "items": {
        "type": "array",
        "items": {
          "type": "number"
        },
        "minItems": 2,
        "maxItems": 2
      },
      "minItems": 3
    },
    "name": {
      "type": "string",
      "description": "Human-readable room name, e.g. 'Office 101'."
    },
    "occupancy": {
      "type": "string",
      "enum": [
        "assembly_concentrated",
        "assembly_standing",
        "assembly_unconcentrated",
        "business",
        "educational_classroom",
        "factory_industrial",
        "healthcare_inpatient",
        "kitchen_commercial",
        "library_reading_room",
        "locker_room",
        "mall_covered",
        "mercantile",
        "parking",
        "residential",
        "storage"
      ],
      "description": "IBC occupancy classification for load-factor lookup. Nominal IBC Table 1004.5 values. Options include: business (9.3 m\u00b2/person), mercantile (2.79 m\u00b2/person), residential (18.58 m\u00b2/person), assembly_concentrated (0.65 m\u00b2/person), etc."
    },
    "wall_thickness": {
      "type": "number",
      "description": "Wall thickness in mm used to compute net area from gross area via the approximation: net = gross \u2212 perimeter \u00d7 (thickness/2). Default 0 (net == gross)."
    },
    "level": {
      "type": "string",
      "description": "Floor / level label for area schedule grouping, e.g. 'L1', 'Ground Floor', 'Level 2'. Default ''."
    }
  },
  "required": [
    "polygon",
    "name",
    "occupancy"
  ]
}
```

---

## `arch_area_schedule`

Produce a building area schedule from a list of rooms. Rolls up total gross area, net area, and occupant load for the whole building and broken down by level and by occupancy type. Each room must be a successful output of arch_room (ok=true). Returns {ok: false, errors: [...]} if any room dict is invalid. Never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "rooms": {
      "type": "array",
      "description": "List of room dicts \u2014 outputs of arch_room (each must have ok=true). Pass an empty list to get an empty schedule.",
      "items": {
        "type": "object"
      }
    }
  },
  "required": [
    "rooms"
  ]
}
```

---

## `arch_occupancy_load`

Compute occupant load and required egress width for a given floor area and occupancy type, without needing a full polygon. Occupant load = ceil(area_m2 / IBC_factor). Egress width: nominal IBC § 1005.1 (0.3 mm/person for stairways, 0.2 mm/person for other means). Load factors: nominal IBC Table 1004.5 values. Returns {ok: false, errors: [...]} on invalid input; never raises.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "area_m2": {
      "type": "number",
      "description": "Floor area in square metres (m\u00b2). Must be >= 0."
    },
    "occupancy": {
      "type": "string",
      "enum": [
        "assembly_concentrated",
        "assembly_standing",
        "assembly_unconcentrated",
        "business",
        "educational_classroom",
        "factory_industrial",
        "healthcare_inpatient",
        "kitchen_commercial",
        "library_reading_room",
        "locker_room",
        "mall_covered",
        "mercantile",
        "parking",
        "residential",
        "storage"
      ],
      "description": "IBC occupancy classification. Nominal IBC Table 1004.5 values. E.g. 'business', 'mercantile', 'assembly_concentrated'."
    },
    "use_net": {
      "type": "boolean",
      "description": "Label the supplied area as 'net' (true, default) or 'gross' (false). Does not affect the numeric calculation."
    }
  },
  "required": [
    "area_m2",
    "occupancy"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
