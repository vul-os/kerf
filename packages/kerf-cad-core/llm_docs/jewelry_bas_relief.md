# jewelry_bas_relief — Bas-Relief / Height-Map Carving for Medals, Coins, and Signet Faces

Convert a 2-D grayscale height map to an indexed-triangle relief mesh for casting or 3-D printing coins, medals, and signet-ring faces. Implements four depth-mapping styles and automatic casting-shrinkage compensation.

## When to use

Use these tools when a jeweller or medallist needs to:
- Convert a grayscale image (portrait, heraldic device, logo) into a castable bas-relief mesh
- Embed a relief mesh into a signet-ring head spec at the correct ring-size inner diameter
- Estimate the displaced metal volume of a relief design for casting cost
- Smooth fine-feature spikes in a relief mesh so they will cast or print cleanly

Keywords: bas relief, height map, relief carving, coin, medal, signet, intaglio, cameo, signet ring, image to mesh, depth map, casting relief, wax bas relief, relief mesh, height field, medal die.

## Depth mapping styles

| Style | Formula | Use case |
|---|---|---|
| `linear` | depth = I × max_depth | Flat / documentary rendering |
| `gamma-curve` | depth = I^γ × max_depth (γ default 0.45) | Shadows deeper; highlights fuller — photographic portraits |
| `sigmoid` | depth = σ(I) × max_depth (S-curve, gain=8) | Clipped highlights and shadows; strong mid-tone contrast |
| `edge-enhanced` | depth = (I + w × |∇²I|) × max_depth (w default 0.25) | Accentuates fine linework, lettering, heraldry |

## Anti-shrinkage and depth cap

- **Casting shrinkage**: 1.5 % linear (gold / silver typical) — `_CASTING_SHRINKAGE = 0.015`
- With `shrinkage_compensation=True` (default) the XY footprint is scaled by 1 / (1 − 0.015) ≈ 1.0152 so the finished cast piece matches `target_dia_mm`
- **Depth cap**: `max_depth_mm` is silently capped at 35 % of `target_dia_mm` to prevent over-deep relief that inverts during casting

## Boundary and border ring

- `boundary = "circular"` — clips the mesh to a disk (default; suits coins, medals, round signet faces)
- `boundary = "square"` — full rectangle mesh
- `border_frac` (default 0.08) — flat border ring around the perimeter as a fraction of the radius; provides a crisp cast edge

## Mesh format

All mesh dicts use:
- `verts` — `list[list[float]]` in mm: `[[x, y, z], ...]`; Z = relief height (0 at back face)
- `faces` — `list[list[int]]`: zero-based triangle indices `[[i0, i1, i2], ...]`

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_image_to_relief` | Read-only: convert a 2-D grayscale intensity grid to a bas-relief triangle mesh; required: `image_rows` (list-of-lists, values 0–1), `target_dia_mm`, `max_depth_mm`; optional `style`, `boundary`, `border_frac`, `gamma`, `edge_weight`, `shrinkage_compensation`, `smooth_passes`; returns `verts`, `faces`, `stats`, `warnings` |
| `jewelry_relief_to_signet` | Read-only: embed a relief mesh into a signet-ring head node spec; required: `relief_mesh`, `signet_face_diameter`, `ring_size`; optional `system` (us/uk/au/eu/jp), `face_height_mm` (default 3.0), `intaglio` (default true = recessed); returns `signet_spec`, `inner_diameter_mm`, `relief_stats`, `warnings` |
| `jewelry_relief_metal_volume` | Read-only: estimate displaced metal volume (mm³) of a relief mesh; required: `relief_mesh`; returns `volume_mm3` |
| `jewelry_optimize_relief_for_casting` | Read-only: smooth fine-feature spikes above the neighbourhood mean by more than `min_feature_mm` (default 0.4 mm) over `smooth_passes` (default 2) rounds; required: `relief_mesh`; returns updated `verts`, `faces`, `delta_features` |

### `jewelry_image_to_relief` output fields

- `verts` — triangle mesh vertices in mm
- `faces` — triangle index list
- `stats` — `{grid_rows, grid_cols, vert_count, face_count, actual_dia_mm, max_depth_mm, style, boundary, border_frac, shrinkage_compensation}`
- `warnings` — depth-cap or grid-size alerts

### `jewelry_relief_to_signet` signet_spec fields

- `op` — `"bas_relief_signet"`
- `face_shape` — `"circular"`
- `face_diameter_mm`, `face_height_mm`, `inner_diameter_mm`
- `intaglio_depth_mm` — maximum depth of the relief
- `mode` — `"recessed"` (intaglio) or `"raised"` (cameo)
- `attach_points` — list of attach-point dicts for the OCCT worker

## Example

Jeweller: "I have a 64 × 64 greyscale portrait of a coat of arms. Make it a 25 mm coin with 1.5 mm max relief using sigmoid style, then embed it in a US size 8 signet ring."

1. `jewelry_image_to_relief` — image_rows=`<64×64 grid>`, target_dia_mm=25, max_depth_mm=1.5, style=`sigmoid`, boundary=`circular`, border_frac=0.08, shrinkage_compensation=true
   → stats: vert_count≈2800, face_count≈5200, actual_dia_mm=25.38

2. `jewelry_relief_metal_volume` — relief_mesh=`<from step 1>` → volume_mm3≈320

3. `jewelry_optimize_relief_for_casting` — relief_mesh=`<from step 1>`, min_feature_mm=0.4, smooth_passes=2 → delta_features=12; smoothed verts

4. `jewelry_relief_to_signet` — relief_mesh=`<smoothed mesh>`, signet_face_diameter=25, ring_size=8, system=`us`, face_height_mm=3.5, intaglio=true
   → inner_diameter_mm=18.13; signet_spec.mode=`recessed`
