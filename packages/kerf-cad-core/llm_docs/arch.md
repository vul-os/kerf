# Architectural BIM Primitives

Pure-Python parametric BIM primitive layer for walls, doors, windows, slabs, and
openings. No OCC geometry produced here — tools return recipe dicts that drive a
downstream worker. All dimensions in **millimetres**.

---

## When to use

Reach for this module when the user asks about:

- drawing or laying out walls, partitions, façades, or boundary walls
- placing doors or windows in a wall; calculating clear opening sizes
- computing wall volumes, net areas (after subtracting openings)
- defining floor/ceiling/roof slabs from a polygon footprint
- adding generic voids, arched openings, or pass-throughs in a wall
- brick/insulation/plaster composite wall layer stacks
- checking whether a door or window fits within a given wall

---

## Tools

### `arch_wall`

Create a parametric wall recipe from a baseline (start/end in plan view), height,
and optional composite layer stack. Returns wall length, gross area, gross volume,
and total thickness. Pass the output to `arch_wall_with_openings` to subtract
hosted openings.

### `arch_door`

Create a parametric door hosted in a wall. Validates that the door fits within
the wall extents. Returns cut-box parameters, opening volume, and panel
configuration. Swing options: `hinged_left`, `hinged_right`, `double`, `sliding`,
`folding`, `pivot`.

### `arch_window`

Create a parametric window hosted in a wall. Accepts sill height (height above
floor). Validates horizontal extent and sill+height against wall height. Returns
cut-box parameters and opening volume. Operation types: `fixed`, `casement`,
`sliding`, `awning`, `hopper`, `tilt_turn`, `louvre`.

### `arch_slab`

Create a parametric horizontal slab (floor, ceiling, or roof deck) from a plan
polygon and thickness. Area is computed via the shoelace formula; volume = area ×
thickness. Accepts an optional Z-level for elevated floors.

### `arch_opening`

Create a generic rectangular or arched (semicircular head) void in a wall. For
arched type, the arch rise = width / 2 is added above the rectangular height.
Validates that the opening fits within the wall extents. Returns cut parameters
and opening volume.

### `arch_wall_with_openings`

Compose a wall with hosted doors, windows, or openings. Computes net wall volume
= gross volume − Σ opening volumes. Accepts output dicts from `arch_wall`,
`arch_door`, `arch_window`, and `arch_opening`. Validates all openings against
wall extents.

---

## Example

**User ask:** "I have a 6 m × 3 m wall, 230 mm thick (brick 110 / insulation 75 /
plaster 45). Add a 900 × 2100 hinged door 600 mm from the left, and a 1200 × 1200
window with 900 mm sill. What is the net wall volume?"

1. `arch_wall` — baseline `[0,0]`→`[6000,0]`, height 3000, layers
   `[{brick,110},{insulation,75},{plaster,45}]`
2. `arch_door` — width 900, height 2100, position_along_wall 600, wall params from step 1
3. `arch_window` — width 1200, height 1200, sill_height 900, position_along_wall 2500
4. `arch_wall_with_openings` — wall from step 1, openings from steps 2 & 3
   → `net_volume_mm3` = gross minus door + window cutouts

---

## Notes

- All tools are **pure-Python**; no OCC dependency.
- Tools are **stateless** — they validate and return dicts; no DB writes.
- Invalid inputs return `{ok: false, errors: [...]}` — never raise.
- `arch_wall_with_openings` accepts outputs from any mix of `arch_door`,
  `arch_window`, and `arch_opening`.
