#!/usr/bin/env node
// ts-check-file.mjs — typecheck a few files against the REAL project config, fast.
//
// WHY THIS EXISTS
// ---------------
// `npm run typecheck` takes 1–3 minutes. That is fine at integration but fatal in a migration
// loop: the Bash tool auto-backgrounds commands over 120s, so an agent that runs it mid-slice
// silently loses its run waiting for output that never arrives. Migration agents therefore need a
// check that returns in seconds.
//
// The obvious workaround — a bare `npx tsc --noEmit --jsx ... <file>` with flags spelled out — is
// WRONG in a way that wastes real time. Passing files positionally makes tsc ignore tsconfig.json
// entirely, so the check loses:
//   * `paths` — every `@/types` import reports TS2307 "cannot find module", plus a cascade of
//     downstream errors on types that failed to load. Observed: 20+ phantom errors in one run.
//   * `types` — `import.meta.env` reports TS2339 without `vite/client`.
// Both are false positives, and the dangerous failure mode is an agent "fixing" one with a
// `@ts-expect-error`. That suppression is unnecessary under the real config, where an unnecessary
// `@ts-expect-error` is itself an error — so the phantom fix becomes a genuine integration break.
//
// This writes a throwaway config that EXTENDS the root one (inheriting paths, types, lib, jsx,
// strictness) and narrows `files` to what you asked for. Same compiler settings as CI, seconds
// instead of minutes.
//
// Usage:  node scripts/ts-check-file.mjs src/components/Foo.tsx [more.tsx ...]
// Exits 0 when clean, non-zero with diagnostics otherwise.

import { writeFileSync, unlinkSync, readdirSync, statSync } from 'node:fs'
import { join, resolve } from 'node:path'
import { spawnSync } from 'node:child_process'

// Ambient declarations are reached through `include` in the real config. Clearing `include` (see
// below) would drop them, and dropping them is not a subtle loss: `src/types/global.d.ts` carries
// `/// <reference types="@webgpu/types" />`, so without it every GPUDevice/GPUBuffer in the
// renderer reports TS2304 "cannot find name". Collect them explicitly instead.
function findAmbient(dir) {
  const out = []
  for (const e of readdirSync(dir)) {
    if (e === 'node_modules' || e.startsWith('.')) continue
    const p = join(dir, e)
    if (statSync(p).isDirectory()) out.push(...findAmbient(p))
    else if (e.endsWith('.d.ts')) out.push(p)
  }
  return out
}

const files = process.argv.slice(2)
if (files.length === 0) {
  console.error('usage: node scripts/ts-check-file.mjs <file.ts(x)> [...]')
  process.exit(2)
}

const root = process.cwd()

// The config must live at the repo root: `extends`, `files` and `paths` all resolve relative to the
// config's own directory, so a temp-dir config would silently point at nothing.
const cfgPath = join(root, `.tsconfig.check.${process.pid}.json`)

writeFileSync(
  cfgPath,
  JSON.stringify(
    {
      extends: './tsconfig.json',
      // `include` must be cleared explicitly — it is inherited, and an inherited `src/**/*` would
      // pull in the whole project and give back the slow full check this script exists to avoid.
      include: [],
      files: [...findAmbient(join(root, 'src')), ...files.map((f) => resolve(root, f))].map(
        (f) => './' + f.slice(root.length + 1),
      ),
    },
    null,
    2,
  ),
)

const r = spawnSync('npx', ['tsc', '-p', cfgPath, '--noEmit'], {
  stdio: 'inherit',
  cwd: root,
})

// Delete BEFORE exiting, not in a `finally`. `process.exit()` terminates the process immediately
// and never unwinds, so a finally-block cleanup silently does not run — which is how two of these
// temp configs ended up committed.
try { unlinkSync(cfgPath) } catch { /* best effort — a leftover temp config is harmless */ }

process.exit(r.status ?? 1)
