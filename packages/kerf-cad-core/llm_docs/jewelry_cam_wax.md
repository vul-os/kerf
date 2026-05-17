# jewelry_cam_wax — Wax-Routing CAM Planner for Jewelry

Jewelry-specific wax-milling workflow that ties together CNC feeds/speeds, 5-axis kinematics, and G-code generation for milling castable wax or resin blanks into ring, pendant, and setting geometries.

## When to use

Use these tools when a machinist or CAM engineer needs to:
- Plan roughing and finishing passes for a jewelry wax blank on a 4-axis or 5-axis CNC
- Handle ring-bore 4-axis indexed passes and 5-axis tilt finishing for the inner diameter
- Select appropriate tools from a library for wax milling (ball-nose, fishtail, flat-end, tapered-ball)
- Check for clamp-proximity collisions before sending the G-code to the machine
- Get cycle-time estimates for a wax-milling job
- Generate per-operation ISO G-code stubs

Keywords: wax routing, CAM wax, jewelry CAM, wax milling, castable wax, 4-axis, 5-axis, ring bore, prong under-reach, collision warning, clamp clearance, roughing strategy, finishing strategy, G-code, cycle time, tool list.

## Machine kinematics schema

```
{
  "type":          str,   // "4axis_indexed" | "5axis_trunnion" | "5axis_head_head"
  "pivot_mm":      float, // distance from rotary pivot to tool tip (mm)
  "a_lo_deg":      float, // A-axis lower limit (default −120°)
  "a_hi_deg":      float, // A-axis upper limit (default +30°)
  "rapid_mm_min":  float, // rapid traverse rate (default 10 000 mm/min)
  "accel_mm_s2":   float, // acceleration (default 500 mm/s²)
}
```

## Tool library entry schema

```
{
  "name":         str,
  "type":         str,    // "ball_nose" | "fishtail" | "flat_end" | "tapered_ball"
  "diameter_mm":  float,
  "flutes":       int,
  "stickout_mm":  float,
  "vc_m_min":     float,  // cutting speed (m/min) for wax
}
```

## Stock block schema

```
{
  "x_mm": float,   // blank dimensions
  "y_mm": float,
  "z_mm": float,
  "material": str  // e.g. "castable_wax" | "blue_wax" | "casting_resin"
}
```

## Jewelry-specific features

- **Ring bore**: auto-plans 4-axis indexed bore passes + 5-axis tilt finishing for the inner diameter
- **Prong under-reach**: tilts finishing tool by `prong_tilt_deg` (default 10°) to clear prong base geometry
- **Clamp proximity warning**: populates `collision_warnings` if piece Y-extent comes within `clamp_clearance_mm` (default 3.0 mm) of stock-block edge

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_plan_wax_routing` | Read-only: master planning function; returns full `WaxRoutingPlan` dict including roughing strategy, finishing strategy, G-code stubs, cycle time, tool list, and collision warnings; required: `piece`, `machine_kinematics`, `tool_library`, `stock_block` |

### WaxRoutingPlan output fields

- `roughing_strategy` — parallel-plane Z-level pass plan: `{pass_count, step_down_mm, step_over_mm, tool_used}`
- `finishing_strategy` — 3-axis surface-finish + 5-axis tilt plan: `{pass_type, tilt_deg, tool_used, scallop_mm}`
- `gcode_stubs` — per-axis ISO G-code line sequences (text)
- `cycle_time_s` — estimated total cycle time (seconds)
- `tool_list` — ordered list of tools actually used
- `collision_warnings` — list of collision / clamp proximity strings
- `ok` — bool; false + `reason` string on hard error

## Example

Machinist: "Plan a wax-milling job for a 6-prong solitaire ring on a 5-axis trunnion machine."

1. `jewelry_plan_wax_routing`:
   - piece = solitaire ring spec from `jewelry_ring_builder`
   - machine_kinematics = {type:"5axis_trunnion", pivot_mm:80, a_lo_deg:-120, a_hi_deg:30}
   - tool_library = [{name:"BN2", type:"ball_nose", diameter_mm:2, flutes:2, stickout_mm:18, vc_m_min:200}, {name:"BN1", type:"ball_nose", diameter_mm:1, flutes:2, stickout_mm:12, vc_m_min:150}]
   - stock_block = {x_mm:25, y_mm:25, z_mm:15, material:"castable_wax"}
   → roughing: 8 Z-passes at 0.5 mm step-down; finishing: 5-axis tilt 10° for prong faces; cycle_time_s=1840; collision_warnings=[]
