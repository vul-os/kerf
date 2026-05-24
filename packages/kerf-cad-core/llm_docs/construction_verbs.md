# Construction Verb Tools (GK-P48)

Sheet-metal hem/jog/multi-flange, direct-edit delete_face and push/pull
(including non-planar faces), and weldment gusset_plate + cope/notch
end-treatments.

---

## When to use

Reach for these tools when the user asks about:

- Adding a hem fold to a bent sheet-metal edge
- Shifting a sheet panel up/down with a jog
- Applying multiple bends in sequence (multi-flange part)
- Deleting a face from a body (with automatic healing)
- Pushing or pulling a flat OR curved face along its normal
- Adding a gusset plate stiffener at a weldment joint
- Preparing weldment member ends with cope or notch cuts

---

## Tools

### Sheet Metal

#### `feature_hem_sheet`

180° hem fold on a bent sheet-metal body. Stiffens edges and removes raw-cut
burrs. Requires the target body to have `__sheet_metal__` with `type == 'bent'`
(output of a `bend_sheet` node).

Styles: `closed` (flat), `open` (with gap), `teardrop` (full teardrop).

**Required:** `file_id`, `target_id`
**Optional:** `style` (default "closed"), `gap` (mm, ≥0), `radius` (default thickness/2), `k_factor` (default 0.44), `id`
**Returns:** `{file_id, id, op:"hem_sheet", style}`

---

#### `feature_jog_sheet`

Z-offset jog (two opposing bends) on a sheet-metal body. Shifts one panel
up/down by `offset` while keeping both panels parallel.

**Required:** `file_id`, `target_id`, `offset` (mm, non-zero)
**Optional:** `jog_angle_rad` (default π/2), `radius` (default 1.0 mm), `k_factor` (default 0.44), `id`
**Returns:** `{file_id, id, op:"jog_sheet", offset}`

---

#### `feature_multi_flange`

Apply a sequence of bends in one call. Each `bend_specs` entry must have:
`bend_line` (absolute X on the flat extent), `angle_rad`, `radius`, optional
`k_factor` (default 0.4).

**Required:** `file_id`, `target_id`, `bend_specs` (non-empty list)
**Optional:** `id`
**Returns:** `{file_id, id, op:"multi_flange", num_bends}`

---

### Direct Edit

#### `feature_delete_face`

Remove a face from a body and attempt to heal the result.
- Planar all-face bodies: re-intersects remaining planes to close the body.
- Curved-face bodies: OCCT uses `BRepTools_ReShape`; pure-Python returns an open shell.

**Required:** `file_id`, `target_id`, `face_id` (0-based)
**Optional:** `heal` (default true), `id`
**Returns:** `{file_id, id, op:"delete_face", face_id}`

---

#### `feature_push_pull`

Offset a face along its outward normal. Positive = outward (add material);
negative = inward (remove material). Supports non-planar faces (GK-P18):
OCCT uses `BRepOffsetAPI_MakeOffsetShape`; pure-Python returns an open shell
with `__direct_edit_curved__ = True`.

**Required:** `file_id`, `target_id`, `face_id`, `distance`
**Optional:** `id`
**Returns:** `{file_id, id, op:"push_pull", face_id, distance}`

---

### Weldment

#### `feature_gusset_plate`

Gusset-plate stiffener at a weldment joint vertex. Computes corner points,
area, and mass.

Shapes: `triangle` (right-triangle, diagonal cut), `rect` (full rectangle),
`trapezoidal` (diagonal top edge).

**Required:** `file_id`, `target_id`, `vertex_pos` ([x,y,z])
**Optional:** `thickness_mm` (default 6), `width_mm` (default 100), `height_mm` (default 100), `shape` (default "triangle"), `fillet_mm` (default 0), `material` (default "steel"), `id`
**Returns:** `{file_id, id, op:"gusset_plate", shape, vertex_pos}`

---

#### `feature_cope_notch`

Cope or notch end-treatment on a weldment member end.
- Cope: rectangular cut-out to fit over a passing member's flange/web.
- Notch: V-cut or square cut at a member corner.

**Required:** `file_id`, `target_id`, `member_index`, `end` ("start" or "end")
**Optional:** `cope_style` / `cope_depth_mm` / `cope_width_mm` / `cope_radius_mm`, `notch_style` / `notch_depth_mm` / `notch_width_mm` / `notch_angle_deg`, `id`
**Returns:** `{file_id, id, op:"cope_notch", end, cope_style, notch_style}`

---

## Example

**User ask:** "Add a closed hem to the bent edge of my sheet part, then apply a
20mm jog to offset a mounting panel."

```
1. feature_hem_sheet
     file_id:"<uuid>"
     target_id:"bend_sheet-1"
     style:"closed"
     k_factor:0.44
   → {id:"hem_sheet-1", op:"hem_sheet", style:"closed"}

2. feature_jog_sheet
     file_id:"<uuid>"
     target_id:"hem_sheet-1"
     offset:20
     radius:2
   → {id:"jog_sheet-1", op:"jog_sheet", offset:20}
```

---

## Notes

- `hem_sheet` requires `__sheet_metal__` metadata with `type == 'bent'`.
- `jog_sheet` / `multi_flange` work with any body carrying `__sheet_metal__` metadata.
- `delete_face` with curved faces may produce an open shell (OCCT only for full healing).
- `push_pull` with curved faces is GK-P18 non-planar push-pull.
- `gusset_plate` is a pure-Python geometry computation — no OCCT.
- `feature_cope_notch` `member_index` is 0-based into the weldment frame member list.
