# gemstones

*Module: `kerf_cad_core.jewelry.gemstones` · Domain: cad*

This module registers **3** LLM tool(s):

- [`jewelry_create_gemstone`](#jewelry-create-gemstone)
- [`jewelry_gem_report`](#jewelry-gem-report)
- [`jewelry_gem_catalog`](#jewelry-gem-catalog)

---

## `jewelry_create_gemstone`

Append a `gemstone` node to a `.feature` file. Generates a parametric gemstone solid with industry-standard proportions. Classic cuts: round_brilliant, princess, oval, emerald, marquise, pear, cushion. Fancy cuts: radiant, asscher, trillion, heart, baguette, briolette. Historical/specialty cuts: old_european, old_mine, rose_cut, single_cut, french_cut, half_moon, trapezoid, kite, bullet, tapered_baguette, lozenge, shield, calf_head. Step/mixed cuts: portuguese (round step+brilliant hybrid), ceylon/barion (brilliant crown + step pavilion), flanders (square brilliant, light corner crop), square_emerald (square step cut, Quadrillion style). Size the stone by carat OR by diameter_mm (long axis for non-round cuts). Carat formula: carat = (diameter_mm / ref_mm)^3 where ref_mm is calibrated per cut and material density (default: diamond, 3.51 g/cm³). Pass material='ruby' (or density_g_cm3=4.00) for accurate coloured-stone carat weights. The gemstone node stores proportions used by the OCCT worker to build a closed solid (pavilion cone + girdle cylinder + crown prism). Use jewelry_cut_gem_seat to cut the matching seat from a ring shank or bezel. Use jewelry_gem_report for a read-only gemologist-style proportion analysis.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "file_id": {
      "type": "string",
      "description": "Target .feature file id (uuid)."
    },
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut style. Classic: round_brilliant=57 facets, princess=square brilliant, oval=elliptical, emerald=rectangular step, marquise=boat, pear=teardrop, cushion=soft square. Fancy: radiant=cropped-corner rectangular brilliant, asscher=square step, trillion=triangular brilliant, heart=heart-shaped, baguette=narrow step cut, briolette=all-facet teardrop. Historical: old_european=high-crown round precursor, old_mine=Victorian cushion, rose_cut=flat-base dome, single_cut=17-facet melee brilliant, french_cut=square step art-deco, half_moon=D-shaped semi-circular, trapezoid=tapered step side stone, kite=arrowhead angular fancy, bullet=pointed-base tapered fancy, tapered_baguette=angled-end bar, lozenge=rhombus step cut, shield=five-sided brilliant, calf_head=wide-pear bouche variant. Step/mixed: portuguese=round step+brilliant hybrid, ceylon=barion brilliant-crown+step-pavilion, flanders=square brilliant light-crop, square_emerald=square step cut (Quadrillion)."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight in carats. Converted to mm via the carat formula. Provide carat OR diameter_mm, not both. For coloured stones supply material or density_g_cm3 for accuracy."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Primary dimension in mm: girdle diameter (round brilliant) or long axis (all other cuts). Provide diameter_mm OR carat, not both."
    },
    "material": {
      "type": "string",
      "description": "Stone material name, e.g. 'diamond', 'ruby', 'sapphire', 'emerald', 'amethyst', 'topaz', 'garnet', 'aquamarine', 'citrine', 'peridot', 'tanzanite', 'opal'. Used for density lookup (carat\u2194mm). Default: 'diamond'."
    },
    "density_g_cm3": {
      "type": "number",
      "description": "Explicit material density in g/cm\u00b3. Overrides material lookup. Use this for unusual stones not in the built-in density table."
    },
    "position": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[x, y, z] placement in model space (mm). Default: [0, 0, 0]."
    },
    "orientation_deg": {
      "type": "array",
      "items": {
        "type": "number"
      },
      "description": "[rx, ry, rz] Euler angles in degrees. Default: [0, 0, 0]."
    },
    "table_pct": {
      "type": "number",
      "description": "Table width override (% of diameter). Optional."
    },
    "crown_angle_deg": {
      "type": "number",
      "description": "Crown angle override (degrees). Optional."
    },
    "pavilion_angle_deg": {
      "type": "number",
      "description": "Pavilion angle override (degrees). Optional."
    },
    "girdle_pct": {
      "type": "number",
      "description": "Girdle thickness override (% of diameter). Optional."
    },
    "aspect_ratio": {
      "type": "number",
      "description": "Width/length ratio override. 1.0=square/round. Default per cut."
    },
    "id": {
      "type": "string",
      "description": "Optional explicit node id."
    }
  },
  "required": [
    "file_id",
    "cut"
  ]
}
```

---

## `jewelry_gem_report`

Read-only gemologist-style report for a gemstone cut + size. Given a cut and either carat or diameter_mm (plus optional material), returns: estimated carat, spread (mm), depth %, table %, length/width ratio, crown and pavilion angle summary, a light-return/proportion grade (Excellent / Very Good / Good / Fair) based on GIA/AGS ideal windows, a 4Cs-style estimate with colour-scale and clarity placeholders (clearly labelled as estimates, not lab grades), and a recommended-setting suggestion for the cut and size. Does NOT write any file — use this to inspect proportions before calling jewelry_create_gemstone.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "cut": {
      "type": "string",
      "enum": [
        "asscher",
        "baguette",
        "briolette",
        "bullet",
        "calf_head",
        "ceylon",
        "cushion",
        "emerald",
        "flanders",
        "french_cut",
        "half_moon",
        "heart",
        "kite",
        "lozenge",
        "marquise",
        "old_european",
        "old_mine",
        "oval",
        "pear",
        "portuguese",
        "princess",
        "radiant",
        "rose_cut",
        "round_brilliant",
        "shield",
        "single_cut",
        "square_emerald",
        "tapered_baguette",
        "trapezoid",
        "trillion"
      ],
      "description": "Gemstone cut style."
    },
    "carat": {
      "type": "number",
      "description": "Stone weight in carats. Converted to mm via the carat formula. Provide carat OR diameter_mm, not both."
    },
    "diameter_mm": {
      "type": "number",
      "description": "Primary dimension in mm (girdle diameter for round_brilliant, long axis for all others). Provide diameter_mm OR carat, not both."
    },
    "material": {
      "type": "string",
      "description": "Stone material for density lookup (e.g. 'diamond', 'ruby', 'sapphire'). Affects carat\u2194mm conversion only.  Default: 'diamond'."
    },
    "density_g_cm3": {
      "type": "number",
      "description": "Explicit material density in g/cm\u00b3. Overrides material lookup."
    }
  },
  "required": [
    "cut"
  ]
}
```

---

## `jewelry_gem_catalog`

Read-only birthstone and gem property catalog. Lookup by gem name (e.g. 'ruby') or birth month (name or 1–12). Returns: birth month(s), Mohs hardness, refractive index, typical density, common cuts, and colour range for each matching gem. Does NOT write any file. Sources: GIA Gem Reference Guide (Liddicoat, 1995), GIA Gemology Reference, GIA Gem Encyclopedia (2014), Jewelers of America birthstone list (2016 revision), AGS birthstone chart, International Gem Society.

### Input schema

```json
{
  "type": "object",
  "properties": {
    "query": {
      "type": "string",
      "description": "Gem name (e.g. 'ruby', 'sapphire', 'morganite') or birth month as English name (e.g. 'january', 'April') or as a number 1\u201312 (e.g. '4' for April). Case-insensitive. Partial name match supported."
    }
  },
  "required": [
    "query"
  ]
}
```

---

## See also

- Package: `kerf_cad_core`
