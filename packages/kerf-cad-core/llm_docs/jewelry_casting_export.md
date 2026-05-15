# Jewelry Casting Export

Production-export tool that emits a casting summary for lost-wax investment casting.
Gemstones are excluded from the cast — only the metal body geometry is exported.

## Tool: `jewelry_casting_export`

Returns a casting summary. Does not require a running OCCT session.

```json
{
  "alloy": "18k_yellow",
  "volume_mm3": 1200.0,
  "thickness_mm": 1.2,
  "gemstone_refs": ["diamond_centre", "ruby_1"]
}
```

`volume_mm3` is the **metal-body volume only** (gems excluded).  
Use `GProp_GProps.Mass()` in mm model units from a CAD volume query.

`gemstone_refs` is optional — list any gem node IDs being excluded for traceability.

---

## Response fields

| Field | Description |
|---|---|
| `alloy` | Resolved alloy key |
| `alloy_label` | Human-readable label (e.g. "18k Yellow Gold") |
| `shrinkage_pct` | Per-alloy casting shrinkage (%) |
| `est_metal_grams` | Net metal weight (g) |
| `est_pour_grams_with_sprue` | Total pour weight including sprue overhead (g) |
| `sprue_count` | Recommended number of sprues |
| `sprue_location` | Gate location description |
| `recommended_orientation` | Flask orientation hint |
| `support_hint` | Wax support strategy |
| `gemstones_excluded` | List of excluded gem refs |
| `stl_available` | `false` via tool path (no OCC shape provided) |

---

## Alloy keys

Same keys as `jewelry_metal_cost`:

```
Gold:      10k_yellow  14k_yellow  18k_yellow  22k_yellow  24k_yellow
           10k_white   14k_white   18k_white   22k_white
           10k_rose    14k_rose    18k_rose    22k_rose
Platinum:  platinum_950  platinum_900
Palladium: palladium_950  palladium_500
Silver:    sterling_925  fine_silver  argentium_935
Other:     titanium  brass  bronze
```

---

## Shrinkage reference (approximate industry midpoints)

| Alloy | Shrinkage |
|---|---|
| 18k yellow gold | 1.25% |
| 18k white gold | 1.30% |
| Platinum 950 | 1.80% |
| Sterling 925 | 1.40% |

Full table in `casting_export.SHRINKAGE_PCT`.

---

## Sprue heuristic (by volume)

| Volume | Sprues | Orientation |
|---|---|---|
| < 500 mm³ | 1 | +Z up |
| 500 – 2 000 mm³ | 1 | +Z up |
| 2 000 – 5 000 mm³ | 2 | +Z tilted 15° |
| > 5 000 mm³ | 3 | caster discretion |

Thin walls < 0.6 mm trigger a cold-shut caution in `support_hint`.

---

## Example: ring in 18k yellow gold

```json
// Request
{
  "alloy": "18k_yellow",
  "volume_mm3": 800,
  "thickness_mm": 1.5,
  "gemstone_refs": ["diamond_centre"]
}

// Response (casting_summary)
{
  "alloy": "18k_yellow",
  "alloy_label": "18k Yellow Gold",
  "shrinkage_pct": 1.25,
  "est_metal_grams": 12.464,
  "est_pour_grams_with_sprue": 13.96,
  "sprue_count": 1,
  "sprue_location": "bottom-centre (thickest cross-section)",
  "recommended_orientation": "+Z up (heaviest section nearest gate)",
  "support_hint": "minimal — thin wax wires at undercuts if present",
  "gemstones_excluded": ["diamond_centre"]
}
```

---

## Shrinkage scale formula

To compute the wax-pattern dimension from a finished metal dimension:

```
wax_dimension = finished_dimension / (1 - shrinkage_pct / 100)
```

Example: 18k yellow, 17.00 mm ring diameter →  
wax pattern = 17.00 / (1 − 0.0125) = **17.215 mm**
