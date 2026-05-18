# Horology generated-parts wishlist

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
`packages/kerf-partsgen/src/kerf_partsgen/generators/horology/<family_id>.py`.

All horology generators use `domain = "horology"` and live under the
`horology/` category path so they appear in the horology persona's catalog.

## Escapement

- [x] Swiss lever escape wheel — wristwatch + pocket watch — id:horology_escape_wheel
- [x] Swiss lever pallet fork — wristwatch + pocket watch — id:horology_pallet_fork

## Gear train

- [x] Horology gear-train wheel — DIN 58400 module series — id:horology_gear_train_wheel

## Barrel

- [x] Horology mainspring barrel — 7¾liga + 11½liga — id:horology_mainspring_barrel

## Future

- [ ] Horology pinion — DIN 58400, leaf counts 6–12 — id:horology_pinion
- [ ] Horology balance wheel — 7¾liga + 11½liga — id:horology_balance_wheel
- [ ] Horology cannon pinion — 7¾liga — id:horology_cannon_pinion
- [ ] Horology click spring — 7¾liga — id:horology_click_spring
