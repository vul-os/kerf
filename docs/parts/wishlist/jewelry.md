# Jewelry generated-parts wishlist

Human-owned. One row per part **family** (never per size). The
`kerf-partsgen` script reads this file but **never writes to it**.

- `- [ ]` — pending: `kerf-partsgen author <family_id>` then
  `kerf-partsgen enumerate` will (re)generate it into `.parts-out/`.
- `- [x]` — **you** reviewed `.parts-out/<domain>/<family>/` by hand and
  approve it. `enumerate` skips `[x]`; `seed` promotes `[x]` into the
  library. Flipping `[ ]`→`[x]` and committing that one line **is** the
  human review record.

`family_id` is the slug of the family name (or an explicit `id:<slug>`
token). It maps to
`packages/kerf-partsgen/src/kerf_partsgen/generators/<family_id>.py`.

All jewelry generators use `domain = "jewelry"` and live under the
`jewelry/` category path so they appear in the jewelry persona's catalog.

## Bracelets / bangles

- [x] Jewelry plain round bangle — wrist sizes S/M/L/XL — id:jewelry_plain_bangle

## Rings

- [ ] Jewelry plain band ring — finger sizes US 4–12 — id:jewelry_plain_band_ring
- [ ] Jewelry signet ring blank — finger sizes US 4–12 — id:jewelry_signet_ring_blank

## Findings

- [ ] Jewelry lobster clasp — nominal lengths 10/12/14/16 mm — id:jewelry_lobster_clasp
- [ ] Jewelry jump ring — wire gauges 18/20/22 AWG, diameters 4/6/8 mm — id:jewelry_jump_ring
