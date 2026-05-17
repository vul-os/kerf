# jewelry_hollowing — Metal Cleanup / Hollowing for Casting Weight Reduction

MatrixGold "Clean Metal" / hollow-out wizard: determine how much of a solid jewelry piece can be hollowed to reach a target casting weight while maintaining structural integrity.

## When to use

Use these tools when a jeweller needs to:
- Hollow out a solid ring, bangle, or pendant to reduce precious metal usage while keeping a minimum wall thickness
- Compute required cavity volume and the maximum feasible cavity given a minimum-wall constraint
- Select a cavity shape (centroid-inset prism, ellipsoid, or lattice infill topology)
- Estimate effective modulus and mass for gyroid / cubic / octet-truss lattice infills using Gibson-Ashby theory
- Determine how many drainage / casting holes to place on hidden faces for wax burnout
- Get a per-stage weight-reduction report with structural integrity flag

Keywords: hollow, hollowing, clean metal, weight reduction, casting weight, minimum wall, cavity, lattice infill, gyroid, octet-truss, drainage hole, polish stock, casting hole, Gibson-Ashby.

## Physics / data references

- **Alloy densities**: resolved from `metal_cost.METAL_DENSITY_G_CM3` (same key space; see jewelry_metal_cost)
- **Gibson-Ashby lattice model**: Gibson, L.J. & Ashby, M.F. "Cellular Solids: Structure and Properties", Cambridge UP, 2nd ed. 1997, Chapter 5
  - `E_eff = C1 × ρ_rel^n × E_solid`
  - gyroid: C1=0.30, n=2.0 (bending-dominated TPMS surface lattice)
  - cubic: C1=1.00, n=1.0 (stretch-dominated open-cell)
  - octet-truss: C1=0.30, n=1.5 (mixed-mode FCC truss)
- **Drainage-hole rule**: minimum 1 hole per 5 000 mm³ cavity; diameter = clamp(0.8, 3.0, 0.5 × V_cavity^(1/3) / 5) mm
- **Structural integrity flag**: warning when cavity exceeds 60% of bounding-box volume

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_hollow_for_weight` | Read-only: given `solid_volume_mm3`, `target_weight_g`, `alloy` (or `density_g_cm3`), and `min_wall_mm` — compute required cavity volume, maximum feasible cavity, recommended cavity shape, and resulting weight |
| `jewelry_lattice_infill` | Read-only: Gibson-Ashby density map for a lattice topology; inputs: `volume_mm3`, `relative_density` (0–1), `cell` (gyroid / cubic / octet_truss), `min_strut_diameter_mm`; returns `E_eff`, `mass_g`, strut count estimate |
| `jewelry_boolean_cleanup_holes` | Read-only: compute drainage/casting-hole count and diameters for a cavity; inputs: `cavity_volume_mm3`, `piece_volume_mm3`; returns hole count and diameter |
| `jewelry_weight_reduction_report` | Read-only: per-stage weight saving %, time-to-cast change estimate, and structural-integrity flag; inputs: `solid_volume_mm3`, `cavity_volume_mm3`, `alloy`, `bbox_volume_mm3` |

## Example

Jeweller: "I have a 3 600 mm³ solid 18k yellow gold bangle. Hollow it to ≤ 12 g keeping 1.0 mm walls."

1. `jewelry_hollow_for_weight` — solid_volume_mm3=3600, target_weight_g=12, alloy=`18k_yellow`, min_wall_mm=1.0 → cavity_volume, shape recommendation
2. `jewelry_boolean_cleanup_holes` — cavity_volume_mm3=`<from step 1>`, piece_volume_mm3=3600 → 1 drainage hole, d=1.2 mm
3. `jewelry_weight_reduction_report` — solid_volume_mm3=3600, cavity_volume_mm3=`<from step 1>`, alloy=`18k_yellow`, bbox_volume_mm3=4200 → weight saved %, integrity_ok=true
