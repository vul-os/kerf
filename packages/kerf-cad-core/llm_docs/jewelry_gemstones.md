# jewelry_gemstones — Parametric Gemstone Generator

Generates parametric gemstone solids with industry-standard proportions for all major cuts; provides a read-only proportion report and a gem property catalog.

## When to use

Use these tools whenever a jeweller needs to:
- Model a specific diamond or coloured-stone cut (round brilliant, princess, oval, emerald, marquise, pear, cushion, radiant, asscher, trillion, heart, baguette, briolette, old European, rose cut, and more)
- Size a stone by carat weight or by mm dimension
- Apply accurate coloured-stone carat estimates (ruby, sapphire, emerald, tanzanite, etc.)
- Inspect proportions and get a GIA-style light-return grade before committing geometry
- Look up birthstone months, Mohs hardness, refractive index, or typical density for any gem species

Keywords: gemstone, diamond, ruby, sapphire, emerald cut, round brilliant, princess cut, oval cut, pear shape, cushion cut, carat, carat weight, 4Cs, facets, girdle, pavilion, crown angle, table percentage, coloured stone, birthstone.

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_create_gemstone` | Appends a `gemstone` node to a `.feature` file; inputs: `file_id`, `cut`, and either `carat` or `diameter_mm`; optional `material`/`density_g_cm3` for coloured stones; returns node id and computed proportions |
| `jewelry_gem_report` | Read-only: given a cut + size (carat or mm) returns spread, depth %, table %, crown/pavilion angles, a light-return grade (Excellent/Very Good/Good/Fair), 4Cs estimate, and recommended setting; does not write any file |
| `jewelry_gem_catalog` | Read-only: lookup by gem name (e.g. "ruby") or birth month (name or 1–12); returns birth month(s), Mohs hardness, refractive index, typical density, common cuts, and colour range |

### Key inputs for `jewelry_create_gemstone`

- `cut` — one of: `round_brilliant`, `princess`, `oval`, `emerald`, `marquise`, `pear`, `cushion`, `radiant`, `asscher`, `trillion`, `heart`, `baguette`, `briolette`, `old_european`, `old_mine`, `rose_cut`, `single_cut`, `french_cut`, `half_moon`, `trapezoid`, `kite`, `bullet`, `tapered_baguette`, `lozenge`, `shield`, `calf_head`, `portuguese`, `ceylon`, `flanders`, `square_emerald`
- `carat` or `diameter_mm` (not both)
- `material` — e.g. `diamond` (default), `ruby`, `sapphire`, `emerald`, `amethyst`, `topaz`, `tanzanite`
- `position` — `[x, y, z]` in mm (default `[0,0,0]`)

## Example

Jeweller: "Add a 1 ct round brilliant diamond centred at the origin, then show me its proportions."

1. `jewelry_gem_report` — cut=`round_brilliant`, carat=1.0 → confirms Excellent grade and 6.5 mm spread
2. `jewelry_create_gemstone` — file_id=`<id>`, cut=`round_brilliant`, carat=1.0 → appends gemstone node
3. Follow with `jewelry_cut_gem_seat` to cut the matching bearing seat into the ring shank
