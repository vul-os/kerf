# jewelry_gem_studio — MatrixGold-Style Gem Studio and Cutter Library

MatrixGold / RhinoGold parity gem studio: produces gemstone solid specs with boolean cutter envelopes for any major cut, provides an extended optical / price catalog, validates metal-wall fit, and auto-sequences melee stone rows.

## When to use

Use these tools when a jeweller needs to:
- Generate a parametric gemstone solid spec AND a ready-to-boolean cutter solid for a ring shank or setting host
- Look up refractive index, dispersion (fire), Mohs hardness, density, GIA colour grades, and price-per-carat orientation for gem materials
- Validate whether a stone cutter will fit within the available metal wall thickness for a chosen setting type
- Auto-size and sequence a row of melee or accent stones to fill a channel of known length

Keywords: gem studio, cutter, boolean cutter, girdle clearance, culet allowance, crown relief, melee, channel layout, gem catalog, refractive index, dispersion, Mohs, price per carat, cabochon, coloured stone, stone fit check, wall thickness.

## Supported cuts

`round_brilliant`, `princess`, `emerald`, `asscher`, `oval`, `marquise`, `pear`, `cushion`, `radiant`, `baguette`, `trillion`, `heart`, `briolette`, `rose_cut`, `cabochon`

## Extended material catalog (GEM_STUDIO_CATALOG)

Sources: GIA Gem Reference Guide (Liddicoat 1995); GIA Gem Encyclopedia 2014; International Gem Society property tables; AGS/GIA 4Cs colour scale; Gemval / GemPrice industry price-per-carat orientation data 2023–2024.

| Material | Density (g/cm³) | RI range | Dispersion | Mohs | Price/ct band (USD orient.) |
|---|---|---|---|---|---|
| diamond | 3.51 | 2.417–2.419 | 0.044 | 10 | $3 000–$25 000 (1 ct round, D-I/VS) |
| ruby | 3.99 | 1.762–1.770 | 0.018 | 9 | $1 000–$30 000 |
| sapphire | 4.00 | 1.762–1.770 | 0.018 | 9 | $500–$20 000 |
| emerald | 2.72 | 1.565–1.602 | 0.014 | 7.75 | $500–$15 000 |
| amethyst | 2.65 | 1.544–1.553 | 0.013 | 7 | $5–$50 |
| aquamarine | 2.72 | 1.567–1.590 | 0.014 | 7.75 | $50–$600 |
| topaz | 3.53 | 1.609–1.643 | 0.014 | 8 | $10–$2 000 |
| garnet | 3.78 | 1.714–1.888 | 0.027 | 7 | $20–$3 000 |
| peridot | 3.32 | 1.650–1.703 | 0.020 | 6.75 | $30–$400 |
| citrine | 2.65 | 1.544–1.553 | 0.013 | 7 | $5–$30 |
| tanzanite | 3.35 | 1.691–1.700 | 0.021 | 6.5 | $300–$1 200 |
| spinel | 3.60 | 1.712–1.762 | 0.026 | 8 | $200–$5 000 |
| tourmaline | 3.10 | 1.624–1.644 | 0.017 | 7.25 | $50–$10 000 |
| opal | 2.08 | 1.370–1.520 | — | 5.75 | $10–$3 000 |
| morganite | 2.71 | 1.572–1.600 | 0.014 | 7.75 | $100–$800 |
| alexandrite | 3.73 | 1.746–1.755 | 0.015 | 8.75 | $5 000–$50 000 |
| moonstone | 2.56 | 1.518–1.526 | 0.012 | 6.25 | $10–$250 |
| zircon | 4.67 | 1.925–1.984 | 0.039 | 6.75 | $50–$400 |

Price data is orientation-only; verify with current market before quoting.

## Minimum metal wall defaults by setting type

| Setting type | Min wall (mm) |
|---|---|
| prong | 0.60 |
| bezel | 0.50 |
| channel | 0.40 |
| pave | 0.35 |
| flush | 0.45 |
| tension | 0.80 |
| bar | 0.50 |

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_gem_studio_cutter` | Read-only: compute gemstone proportions dict + boolean cutter envelope for any cut; size by `carat` or `diameter_mm`; configurable `girdle_clearance_mm` (default 0.05), `culet_allowance_mm` (0.10), `crown_relief_mm` (0.30), `table_offset_mm` (0.05), `seat_allowance_mm` (0.02) |
| `jewelry_gem_studio_catalog` | Read-only: look up optical properties, colour grades, hardness, price orientation; query by `material` name or by `cut` name (returns materials commonly used with that cut) |
| `jewelry_gem_studio_fit_check` | Read-only: validate cutter envelope against available metal wall thickness; pass the `cutter` sub-dict from `jewelry_gem_studio_cutter`; returns `ok`, `clearance_mm`, and warnings |
| `jewelry_gem_studio_melee_seq` | Read-only: auto-size and sequence a row of melee/accent stones into a channel; returns stone count, pitch, centre positions, and per-stone cutter spec; size by `target_carat` or `target_diameter_mm` |

## Cutter envelope fields

The `cutter` sub-dict returned by `jewelry_gem_studio_cutter` contains:
- `girdle_long_radius_mm`, `girdle_short_radius_mm` — cutter radii at girdle plane
- `cutter_depth_mm` — total axial depth of the cutter solid
- `crown_relief_mm` — depth of crown countersink
- `girdle_ledge_mm` — ledge height where girdle rests
- `pavilion_depth_mm` — depth of pavilion zone
- `bounding_long_axis_mm`, `bounding_short_axis_mm` — overall cutter extent (used by fit check)

## Example

Jeweller: "I want a 0.50 ct round brilliant melee row in a 20 mm channel. Check the cutter fits a 1.2 mm bezel wall."

1. `jewelry_gem_studio_melee_seq` — cut=`round_brilliant`, channel_length_mm=20, target_carat=0.05 → stone count, positions, cutter_spec
2. `jewelry_gem_studio_fit_check` — cutter=`<cutter from step 1>`, wall_thickness_mm=1.2, setting_type=`bezel` → ok=true, clearance_mm=…
