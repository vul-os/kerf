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

## Agent worktree base — read before launching a slice agent

Agent worktrees are **not reliably created from the current tip.** Observed behaviour: some
worktrees branch from the live integration tip, others from the commit that was `HEAD` when the
session started — even when `main` is well ahead of it. Three separate slice runs were launched
against a base with no `tsconfig.json` and no `src/types/`.

**Do not rely on the worktree's base being right. Have the agent fix it.** Because all worktrees
share one repository, every branch ref is visible from inside them, so an agent can self-heal.
Open every slice prompt with:

```
git merge main --no-edit                      # main is the integration branch and is ahead
ls tsconfig.json tsconfig.strict.json         # T-500
ls src/types/index.ts src/types/geometry.ts   # T-501
ls scripts/lint-ts-ratchet.mjs                # the lint gate
```

The merge is a fast-forward whenever the stale base is an ancestor of `main`, which it has been in
every case so far. Instruct the agent to **stop and report** if it is *not* a fast-forward, or if a
path is still missing afterwards — that would mean the repo is not in the expected state, and
building on it would be worse than pausing.

**Corollary rule:** after any slice is verified green, fast-forward `main` immediately. `main` is
the integration branch that worktrees heal against, so a stale `main` breaks every subsequent
agent.

### `node_modules` — symlink it, never reinstall it

Worktrees have no `node_modules`, and this repo's is **982 MB**. Several agents burned their
opening minutes on `npm ci` / `npm install`, and one stalled before it even finished. Symlink the
main checkout's instead — verified working for `tsc`, `vitest` and `eslint`:

```
ln -s /Users/pc/code/vulos/kerf/node_modules node_modules
```

Add this to the base-fix block of every slice prompt. It is near-instant, costs no disk, and
removes a long unprotected window at the start of each run. Agents must not run `npm install` in a
worktree afterwards — it would mutate the shared tree that every other agent is reading.

The cheap base check at the top of a prompt has already converted three would-be wasted runs into
clean sub-minute no-ops. It earns its lines.

## Known traps when verifying a slice

1. **`npm run lint` is RED at baseline** — ~1,451 pre-existing errors in the un-migrated
   `.js`/`.jsx` tree. Real debt, but not G1's. **Gate on `npm run lint:ts:ratchet`.**

   It is a **ratchet, not a hard zero** — and the reason matters. Migrating a file *renames* it,
   so its pre-existing lint debt **moves** from the `lint` bucket into `lint:ts`; nothing new is
   created. This was measured, not assumed: linting the pre-migration `.js` of a representative
   file produced the identical error. A hard-zero gate would therefore fail a slice for problems
   it did not cause.

   The ratchet enforces the invariant that actually matters: **the count may never rise**, and
   when it falls you must lower `BASELINE` in `scripts/lint-ts-ratchet.mjs` so the cleanup is
   locked in. Current baseline: **78** inherited errors. Target is 0.

   If your slice raises the count, you added the debt — fix it. Never raise the baseline.

4. **Tests that read source by literal path will break on rename.** Several suites do
   "source-text inspection" — e.g. `GdsLayoutPage.test.jsx` did `readFileSync('lib/gdsLoader.js')`.
   Renaming the module broke it, and it is not caught by typecheck, only by running the suite.
   After migrating, grep for literal `'lib/<name>.js'` style references and update them. Note the
   distinction: an **import specifier** ending `.js` is still correct (it resolves to `.ts` under
   `moduleResolution: bundler`); only literal filesystem paths need changing.
2. **`npm test` intermittently exits 1 while reporting every test passed.** The cause is an
   `EnvironmentTeardownError` unhandled rejection — a late dynamic import racing environment
   teardown, observed in `src/lib/panels/__tests__/dcc.test.jsx` but not specific to it. It is
   nondeterministic: a re-run passes clean. Check the pass counts, not just the exit code. Do not
   try to fix it inside a slice.
3. **Do not run full-package Python/pytest suites** from a frontend slice, and **do not spawn
   sub-agents.** Both consumed large amounts of time earlier in this program for zero benefit. An
   additive diff cannot regress a suite it does not touch.

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

## Shared types (T-501)

`src/types/` holds every domain contract a slice needs so agents don't each invent their own.
Every type is derived from how the code actually behaves (JSDoc `@param`, header-comment
protocols, canonical entity-creation call sites) — none are guessed. Where a shape was genuinely
open-ended in the source, the file says so inline and narrows to `unknown` or a bounded record
rather than `any`.

| File | Contents |
|---|---|
| `src/types/geometry.ts` | `Vec3`/`Vec2`, `BBox`/`BBox2`, `Geom3`/`Geom2` (re-exported from `@jscad/modeling`, not redeclared), `Mesh`/`FaceMeta`/`EdgeMap`/`FaceNameMap` (the occtWorker triangulation wire format), `FaceDescriptor`/`ModifiedMap` (face naming), `SketchJSON` and its entity/constraint/plane unions, `FeatureNode` (discriminated by `op`, ~28 named CAD-op variants plus a bounded jewelry-domain catch-all) and `FeatureFile`, `AssemblyDocument` and its component/mate/override shapes |
| `src/types/circuit.ts` | `CircuitElement`/`CircuitJson` — the **alias seam** over `circuit-json`'s `AnyCircuitElement`/`CircuitJson`. G2 repoints this one file when it replaces Circuit JSON with a Kerf-native ECAD IR; no other file should import from `circuit-json` directly |
| `src/types/workers.ts` | Request/response discriminated unions for the occt, jscad and circuit Web Workers, plus the main-thread runner envelopes (`OcctRunFeaturesResult`, `JscadRunResult`, `CircuitCompileResult`) that wrap `stale`/`error` handling on top of the raw postMessage shapes |
| `src/types/api.ts` | Response shapes for `src/lib/api.js`'s ~80 endpoint methods, grouped by resource (auth, workspaces, projects, files, threads, members/sharing, revisions, activity, BOM, uploads, admin, and the various domain-specific tool endpoints that document their own return shape in a source comment) |
| `src/types/index.ts` | Barrel — slice agents should import from `src/types` (or `@/types`) rather than reaching into a sibling file directly |

`src/types/global.d.ts` is **T-500**'s file (toolchain/ambient declarations) and is not
re-exported from the barrel — see that file's own header comment.

**Convention for adding a new shared type:** put it in the file matching its domain (geometry,
circuit, worker protocol, or API response); export it from that file so the barrel picks it up
automatically. Slice agents may **append** a new type as their slice needs it. *Changing* an
existing shared type's shape is this task's owner's call — every other slice depends on it, so
open a discussion rather than editing in place. Never redeclare a domain type locally in a slice
file; if the shape you need is missing here, that's the gap to fill, not a local workaround.

## Tightening (T-521 / T-522)

`tsconfig.strict.json`'s `include` list only ever grows, one directory per commit, each gated by
`npm run typecheck:strict` in CI. A directory that has been tightened cannot silently regress.
When T-522 closes, the root config flips to `strict: true` and `tsconfig.strict.json` is deleted.

## Definition of done for G1

`find src -name "*.js" -o -name "*.jsx"` returns **zero** files, root `tsconfig` runs
`strict: true`, and the vitest pass count is ≥ the baseline above.
