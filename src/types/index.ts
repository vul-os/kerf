// index.ts — barrel for src/types/ (T-501).
//
// Slice agents (T-502...T-519): import shared domain types from `src/types`
// (or `@/types`, per the `paths` alias in tsconfig.json), not from these
// sibling files directly — e.g. `import type { FeatureNode } from '@/types'`.
// See docs/typescript-migration.md's "Shared types (T-501)" section for the
// convention on where a *new* shared type belongs.
//
// `src/types/global.d.ts` is deliberately not re-exported here — it's an
// ambient declaration file (T-500), nothing to import.
//
// `export type *` (not plain `export *`): under `isolatedModules` (set in tsconfig.json), a
// per-file transpiler can't know whether a sibling module has any value exports, so a plain
// `export *` from an all-types module can't be safely elided and would still emit a runtime
// re-export. Since every sibling file here is contractually types-only, `export type *` makes
// that guarantee explicit and enforced by the compiler rather than by convention — this barrel
// itself must emit nothing.

export type * from './geometry'
export type * from './circuit'
export type * from './workers'
export type * from './api'
