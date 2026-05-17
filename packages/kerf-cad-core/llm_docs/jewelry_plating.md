# jewelry_plating — Multi-Layer Metal Plating Specification

Multi-layer metal / plating specification for layered jewelry (18k-over-silver, vermeil, rhodium-over-white-gold, gold-fill). Computes plating mass, validates hallmark / legal requirements, checks wear class, and flags incompatible base / plate combinations.

## When to use

Use these tools when a jeweller needs to:
- Specify a plating stack (base metal + one or more deposited layers)
- Compute the mass contribution of each plating layer (volume = coverage × thickness)
- Verify vermeil requirements (≥ 2.5 µm gold over sterling silver per FTC rules)
- Check whether a base/plate combination has known incompatibility issues
- Determine the correct hallmark for a plated piece (base metal hallmark + "plated" qualifier)
- Assess wear suitability for light / medium / heavy / extreme use

Keywords: plating, rhodium, rhodium plate, vermeil, gold plate, gold-filled, rolled gold, gold over silver, silver base, electroplate, electroforming, hallmark plating, FTC hallmark, wear class, tarnish bleed, pink bleed, nickel barrier, copper migration.

## Layer physics

- Layer volume (mm³) = `coverage_mm2` × `thickness_um` × 1e-3
- Layer mass (g) = layer_volume_mm3 × `density_g_cm3` / 1000
- Densities are resolved from `metal_cost.METAL_DENSITY_G_CM3`

## Hallmark / legal rules

**US (FTC):**
- "vermeil": ≥ 2.5 µm of 10k+ gold over sterling silver 925
- Plated items must be marked "gold plated" / "GP"; base hallmark applies
- Rhodium plating does not affect the gold hallmark of the base

**UK / EU (Hallmarking Act + CIBJO):**
- Plated items cannot carry an independent precious-metal hallmark for the plating layer
- Base metal hallmark (e.g. 925 for sterling) remains; must also state "plated"
- No statutory EU minimum for "vermeil"; FTC 2.5 µm rule commonly applied

**General:**
- "rhodium plated" / "Rh" suffix allowed alongside base hallmark
- Plated ≠ alloyed; fineness stamp reflects base only

## Wear classes

| Class | Typical use |
|---|---|
| `light` | Occasional wear — decorative pendants, earrings rarely touched |
| `medium` | Daily wear but protected — most rings, bracelets |
| `heavy` | High-friction daily wear — ring shanks, clasps, watch bezels |
| `extreme` | Industrial or working jeweller tools, tool-grade surfaces |

## Known incompatibility flags

- Silver base + very thin gold plate (< 0.5 µm): silver tarnish diffuses through pinholes ("tarnish bleed-through")
- Copper-rich base (brass, bronze) + thin gold: copper migration ("pink bleed") without a nickel barrier layer
- Titanium base: poor adhesion for standard electroplating without PVD pre-treatment
- Palladium plate over palladium base: functionally redundant (warning only)

## Tools

| Tool | Description |
|------|-------------|
| `jewelry_plating_spec` | Read-only: compute per-layer mass, total plating mass, hallmark guidance, and incompatibility flags for a multi-layer plating stack; required: `base_alloy`, `layers` array |
| `jewelry_plating_vermeil_check` | Read-only: verify whether a gold-over-silver plating stack qualifies as vermeil under FTC rules; required: `plate_alloy`, `plate_thickness_um`, `base_alloy` |

### Layer dict schema

Each element of `layers`:
```
{
  "alloy":         str,    # alloy key from metal_cost (e.g. "18k_yellow", "rhodium")
  "thickness_um":  float,  # layer thickness in microns (µm)
  "coverage_mm2":  float   # surface area covered (mm²)
}
```

## Example

Jeweller: "I want 18k yellow gold vermeil earrings (silver base, gold plate). Check the FTC rules."

1. `jewelry_plating_vermeil_check` — base_alloy=`sterling_silver_925`, plate_alloy=`18k_yellow`, plate_thickness_um=3.0 → ok=true; ≥ 2.5 µm gold on 925 silver — qualifies as FTC vermeil
2. `jewelry_plating_spec` — base_alloy=`sterling_silver_925`, layers=[{alloy:`18k_yellow`, thickness_um:3.0, coverage_mm2:450}] → mass_g=0.031 g gold layer; hallmark=`925 gold plated`
