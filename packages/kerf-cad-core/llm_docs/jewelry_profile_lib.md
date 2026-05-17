# jewelry_profile_lib — Parametric 2D Ring-Profile Library

MatrixGold / RhinoGold parity: parametric 2D cross-section profile library for ring shanks, bangles, and wire jewellery. Returns geometry and section properties (area, centroid, second moments of area, perimeter, inner/outer radii).

## When to use

Use these tools when a jeweller needs to:
- Pick or compare a named ring shank cross-section before sweeping it along the ring bore path
- Get section properties (area, moment of inertia) for a ring band profile
- Compare comfort-fit ergonomics of different profile shapes qualitatively
- Confirm which profiles are available and what parameters they accept

Keywords: ring profile, shank profile, cross-section, comfort fit, court shape, knife edge, D-shape, half round, flat band, bombe, bevelled, double bombe, channel-ready, comfort edge, profile library, sweep profile, ring band section.

## Coordinate convention

Profile is in the XY plane:
- X-axis: across the band width (labial direction, finger-to-finger)
- Y-axis: radial direction (+Y = outside skin, −Y = bore touching finger)
- Origin at the centroid of the outer bounding rectangle

## Named profiles

| Profile name | Description |
|---|---|
| `comfort_fit` | Rounded inside, sharp/flat outside — standard comfort-fit (most popular modern) |
| `court` | Rounded outside, flat inside — classic UK "court" shape |
| `flat` | Rectangular cross-section, sharp corners throughout |
| `half_round` | Semicircle outside, flat inside |
| `d_shape` | D-profile: flat inside, full round outside |
| `knife_edge` | V-wedge, apex at +Y (sharp outside edge) |
| `square` | Square cross-section (width = thickness) |
| `rectangle` | Alias for `flat` |
| `stamped_edge` | Flat with two symmetric edge-radius fillets on the outside corners (rolled / pressed look) |
| `bombe` | Domed outside + flat inside |
| `bevelled` | Flat with four straight chamfers at corners |
| `double_bombe` | Bombe profile mirrored: convex both sides (lens section) |
| `flat_with_comfort_edge` | Flat with comfort-fit rounding only at inside corners |
| `channel_ready` | Flat band with a central groove on the outside face for stone channel setting |
| `knife_bombe` | Knife-edge outside + bombe (dome) inside |

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_list_profiles` | Read-only: list all catalogue entries with name, description, and accepted parameter names; optional `family` filter |
| `jewelry_get_profile` | Read-only: compute one profile by name + dimension params; returns polyline, section area, perimeter, I_x, I_y, inner/outer radii, centroid |
| `jewelry_compare_comfort` | Read-only: qualitative ergonomic comparison of two profiles — rates comfort, wearability, and metal-weight difference |

### `jewelry_get_profile` key inputs

- `name` — profile name from the table above
- `width_mm` — band width (X-extent)
- `thickness_mm` — wall thickness (Y-extent, outer to inner bore)
- `inner_radius_mm` — inner-face rounding radius (applies to comfort_fit, court, etc.)
- `outer_radius_mm` — outer-face rounding radius (applies to court, d_shape, bombe, etc.)
- `chamfer_mm` — chamfer size (applies to bevelled, stamped_edge)
- `groove_width_mm`, `groove_depth_mm` — groove dimensions (applies to channel_ready)

### Section properties returned

- `area_mm2` — cross-section area
- `perimeter_mm` — outer perimeter
- `centroid_mm` — `[x, y]` in section plane
- `I_x_mm4`, `I_y_mm4` — second moments of area
- `polyline` — list of `[x, y]` points bounding the profile

## Example

Jeweller: "Compare comfort-fit vs court profile for a 5 mm × 2.2 mm wedding band."

1. `jewelry_get_profile` — name=`comfort_fit`, width_mm=5, thickness_mm=2.2, inner_radius_mm=1.0 → area, centroid, polyline
2. `jewelry_get_profile` — name=`court`, width_mm=5, thickness_mm=2.2, outer_radius_mm=1.5 → area, centroid, polyline
3. `jewelry_compare_comfort` — profile_a=`comfort_fit`, profile_b=`court`, width_mm=5, thickness_mm=2.2 → comfort rating, wearability notes, weight delta
