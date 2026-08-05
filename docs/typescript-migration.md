# TypeScript migration (G1) — conventions and coordination

Companion to ROADMAP §*Active program* and `tasks.md` T-500 … T-524. This document is the
**authoritative coordination surface** for concurrent migration agents. If it and a task entry
disagree about who owns a file, fix this document first, then re-run.

## The invariant

> **The build stays green at every commit.**

Everything else here follows from that. It is what makes N agents on disjoint slices safe. An
agent that cannot land its slice green **reverts and reports** — it does not merge red and it does
not widen its slice to chase a fix.

## Toolchain (T-500, landed 2026-08-05)

| Piece | File | Notes |
|---|---|---|
| Gradual config | `tsconfig.json` | `allowJs: true`, `checkJs: false`, `strict: false`, `noEmit: true` |
| Strict ratchet | `tsconfig.strict.json` | `strict: true` over an **append-only** directory allow-list |
| Typecheck | `npm run typecheck` | `tsc --noEmit`, root config |
| Strict typecheck | `npm run typecheck:strict` | the ratchet; CI-gated |
| Lint | `npm run lint` | `typescript-eslint` recommended (not type-aware yet) |
| CI | `.github/workflows/typecheck.yml` | typecheck → strict → lint → vitest |

**TypeScript is pinned to `^5.9.3` on purpose.** `typescript@*` resolves to 7.0.2, but
`typescript-eslint@8` peers at `typescript >=4.8.4 <6.1.0`, so TS 7 costs type-aware linting. For a
migration whose entire point is correctness, working lint beats a faster compiler. Revisit when
typescript-eslint supports the 7.x line.

**Vite needed no configuration change** — it resolves and transpiles `.ts`/`.tsx` natively, and
vitest's default include globs already collect `*.test.ts`. Both verified.

## Baseline — measured 2026-08-05, before any slice

Re-measure before claiming a delta. Do not quote these numbers as current.

| Metric | Value |
|---|---|
| `src/` `.js` | 499 files / 127,956 lines |
| `src/` `.jsx` | 695 files / 238,717 lines |
| `src/` `.ts` / `.tsx` | 0 / 0 |
| Colocated test files | 466 |
| **vitest** | **477 files, 13,192 passed, 22 skipped** |
| `npm run build` | clean |
| Largest file | `src/lib/occtWorker.js` — 7,957 lines |

## Conventions

1. **Rename, don't rewrite.** A slice converts `.js` → `.ts` and adds types. Behaviour changes,
   refactors and "while I'm here" cleanups belong in separate tasks. A migration diff that also
   changes logic cannot be reviewed.
2. **Migrate colocated tests with their source.** `foo.js` + `foo.test.js` move together.
3. **`any` is a boundary tool, not a default.** Allowed at an interface the slice does not own;
   must carry an inline comment saying why. Lint reports it as a warning now and an error after
   T-521/T-522.
4. **`@ts-ignore` is banned** — use `@ts-expect-error` with a description, so a suppression that
   stops being necessary becomes an error instead of rotting silently.
5. **Import extensions:** keep `.js` specifiers when importing un-migrated modules; TypeScript
   resolves them correctly under `moduleResolution: bundler`.
6. **Shared types come from `src/types/`.** Never redeclare a domain type locally — if the shape
   you need is missing, that is a T-501 change, not a slice change.

## Ownership

- `src/types/global.d.ts` — **T-500** (toolchain: bundler/platform ambient declarations).
- `src/types/*.ts` domain types — **T-501**. Slice agents may **append** new types; *changing* an
  existing shared type is T-501's owner's call, because every other slice depends on it.
- Everything else — one slice, one owner, per the task entries in `tasks.md`.

### Slice manifests

Directory-scoped slices (T-502…T-512, T-518, T-519) are unambiguous: the task names whole
directories, and the agent owns every `.js`/`.jsx` in them.

The five `src/components/` top-level slices (T-513…T-517) split one flat 299-file directory by
role, so they need an **explicit file manifest generated before those agents start**. Generate it
with `scripts/ts-slice-manifest.mjs` (T-513's first step) and paste the result here. Until that
manifest exists, do not run T-513…T-517 concurrently.

## Tightening (T-521 / T-522)

`tsconfig.strict.json`'s `include` list only ever grows, one directory per commit, each gated by
`npm run typecheck:strict` in CI. A directory that has been tightened cannot silently regress.
When T-522 closes, the root config flips to `strict: true` and `tsconfig.strict.json` is deleted.

## Definition of done for G1

`find src -name "*.js" -o -name "*.jsx"` returns **zero** files, root `tsconfig` runs
`strict: true`, and the vitest pass count is ≥ the baseline above.
