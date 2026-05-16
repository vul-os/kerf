# Metal Casting Design (Groover / Campbell / AFS)

Pure-Python metal casting design tools covering shrinkage allowances, gating
system sizing, riser design, Chvorinov solidification time, yield, and pouring
guidance. No OCC dependency. Units: SI (m, kg, s) and degrees.

---

## When to use

Use these tools when the user asks about sand casting, investment casting,
foundry design, pattern allowances, draft angles, solidification time,
risers/feeders, gating systems (sprue, runner, gate), casting yield, or
pouring temperature.

Keywords: casting, foundry, shrinkage allowance, draft angle, Chvorinov,
solidification, riser, feeder, gating, sprue, runner, gate, casting yield,
pouring temperature, fluidity, sand mold, pattern, alloy, porosity.

Supported alloys: `grey_cast_iron`, `white_cast_iron`, `ductile_iron`,
`carbon_steel`, `stainless_steel`, `aluminium_alloy`, `copper_alloy`,
`bronze`, `zinc_alloy`, `magnesium_alloy`, `nickel_alloy`, `titanium_alloy`.

---

## Tools

### `casting_shrinkage_allowance`

Pattern dimension after shrinkage compensation and machining stock.

The pattern must be made larger to account for solidification shrinkage and
machining stock. Returns the required pattern dimension in mm.

**Input:**
- `alloy` (required) — alloy enum (see above)
- `nominal_dim_mm` (required) — final desired casting dimension (mm)
- `extra_machining_mm` — additional machining stock per surface (mm; default 0)

**Returns:** `pattern_dim_mm`, `shrinkage_rate`, `machining_stock_mm`

---

### `casting_draft_angle_volume`

Extra volume added to a pattern face by a draft angle taper.

Volume ≈ base_area × height × tan(draft_deg).

**Input:** `base_area_m2`, `height_m`, `draft_deg` (all required, draft typically 0.5°–5°)

**Returns:** `added_volume_m3`, `added_volume_mm3`

---

### `casting_chvorinov`

Solidification time via Chvorinov's Rule: t = B·(V/A)^n.

**Input:** `volume_m3`, `area_m2` (required); `B` (mold constant s/m², default 600); `n` (exponent, default 2.0)

**Returns:** `solidification_time_s`, `modulus_m` (= V/A), `B`, `n`

---

### `casting_riser_size`

Riser size by modulus method: M_riser ≥ 1.2 × M_casting.

For cylindrical riser (H = D): D_min = 6 × M_casting.

**Input:** `casting_volume_m3`, `casting_surface_area_m2` (required); `alloy` (default carbon_steel); `riser_shape` (enum: cylindrical); `B`, `n`

**Returns:** `M_casting_m`, `M_riser_min_m`, `D_riser_m`, `D_riser_mm`,
`riser_volume_m3`, warning if riser insufficient

---

### `casting_gating_system`

Design gating system (sprue / runner / gate) areas via Bernoulli + continuity.

v = Cd·√(2·g·H);  A_choke = (m/ρ)/(t_pour·v)

Ratios — unpressurised (default, choke at sprue): 1:2:4;
pressurised (choke at gate): 1:0.75:0.5.

**Input:** `casting_mass_kg`, `alloy`, `pouring_time_s`, `sprue_height_m` (all required); `system_type` (`'unpressurised'`/`'pressurised'`); `discharge_coeff` (default 0.85)

**Returns:** `A_choke_m2`, `A_sprue_m2`, `A_runner_m2`, `A_gate_m2`,
`velocity_ms`, `metal_density_kg_m3`

---

### `casting_yield`

Casting yield % = (casting_mass / total_poured) × 100.

Warns if yield < 60% (poor economics) or < 50% (redesign needed).

**Input:** `casting_mass_kg`, `total_poured_mass_kg` (both required)

**Returns:** `yield_pct`, `gating_riser_mass_kg`, warnings

---

### `casting_pouring_guidance`

Recommended pouring temperature range and fluidity notes for an alloy and minimum section.

Warns for thin sections: ferrous < 5 mm, Al/Mg < 3 mm, other non-ferrous < 2 mm.

**Input:** `alloy`, `section_thickness_mm` (both required)

**Returns:** `T_pour_low_C`, `T_pour_high_C`, `fluidity_notes`, warnings for thin sections

---

## Example

```
1. casting_shrinkage_allowance  alloy:"aluminium_alloy"  nominal_dim_mm:150.0
   → pattern_dim_mm: 152.4  shrinkage_rate: 0.013  machining_stock_mm: 1.5

2. casting_chvorinov  volume_m3:0.002  area_m2:0.12
   → solidification_time_s: 694  modulus_m: 0.0167

3. casting_riser_size  casting_volume_m3:0.002  casting_surface_area_m2:0.12
   → D_riser_mm: 100.0  riser_volume_m3: 7.85e-4

4. casting_gating_system  casting_mass_kg:15.6  alloy:"aluminium_alloy"
                          pouring_time_s:8  sprue_height_m:0.25
   → A_sprue_m2: 3.8e-4  A_runner_m2: 7.6e-4  A_gate_m2: 1.52e-3

5. casting_yield  casting_mass_kg:15.6  total_poured_mass_kg:22.0
   → yield_pct: 70.9  (acceptable)
```
