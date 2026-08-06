#!/usr/bin/env node
// lint-ts-ratchet.mjs — G1 lint gate for the migrated TypeScript tree.
//
// WHY THIS EXISTS
// ---------------
// The first version of this gate asserted `lint:ts` must be exactly 0, on the assumption that
// newly-migrated files start clean. That assumption was wrong, and it was measured to be wrong:
// linting the pre-migration `.js` of a representative file produced the *identical* error. A
// migration RENAMES a file, so its pre-existing lint debt simply MOVES from the `npm run lint`
// bucket into the `lint:ts` bucket. Nothing was created; the debt was already there.
//
// So a hard zero would fail CI for problems the slice did not cause, which is exactly the
// "red CI that everyone learns to ignore" outcome the gate is meant to prevent.
//
// Instead this is a RATCHET, the same shape as tsconfig.strict.json:
//   - the error count may never INCREASE  -> a slice cannot add new lint debt
//   - when it decreases, the baseline must be lowered -> cleanup is locked in permanently
//
// The end state is BASELINE = 0, at which point this script can be replaced by a plain
// `eslint` invocation. Lowering the number is always correct; raising it needs a reason.

import { execFileSync } from 'node:child_process'

// Inherited (not introduced) lint errors across the migrated .ts/.tsx tree.
// Measured 2026-08-05 after T-502 landed 191 src/lib modules.
// Lowered to 73 by T-505 (2026-08-06): migrating orphaned lib tests surfaced
// unused-vars in previously-untyped-and-unlinted padOverrides/pcbRouting/
// viaStitching source, fixed in place rather than left at the old count.
// This number may only ever go DOWN.
const BASELINE = 73

const args = [
  'eslint',
  '--no-error-on-unmatched-pattern',
  '--format', 'json',
  'src/**/*.ts',
  'src/**/*.tsx',
]

let raw = ''
try {
  raw = execFileSync('npx', args, { encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 })
} catch (err) {
  // eslint exits non-zero when it finds problems; the JSON report is still on stdout.
  raw = err.stdout ?? ''
  if (!raw) {
    console.error('lint-ts-ratchet: eslint produced no report.')
    console.error(err.stderr ?? err.message)
    process.exit(2)
  }
}

let report
try {
  report = JSON.parse(raw)
} catch {
  console.error('lint-ts-ratchet: could not parse the eslint JSON report.')
  process.exit(2)
}

const errors = report.reduce((n, f) => n + f.errorCount, 0)
const warnings = report.reduce((n, f) => n + f.warningCount, 0)
const files = report.filter((f) => f.errorCount > 0).length

if (errors > BASELINE) {
  console.error(
    `lint-ts-ratchet: FAIL — ${errors} errors across ${files} files, baseline is ${BASELINE}.\n` +
    `This slice ADDED ${errors - BASELINE} lint error(s) to the TypeScript tree.\n` +
    `Fix them; do not raise the baseline. Run \`npx eslint "src/**/*.ts" "src/**/*.tsx"\` for detail.`
  )
  process.exit(1)
}

if (errors < BASELINE) {
  console.error(
    `lint-ts-ratchet: FAIL — ${errors} errors, but the baseline says ${BASELINE}.\n` +
    `You cleaned up ${BASELINE - errors} error(s). Lower BASELINE to ${errors} in ` +
    `scripts/lint-ts-ratchet.mjs so the improvement is locked in and cannot regress.`
  )
  process.exit(1)
}

console.log(
  `lint-ts-ratchet: OK — ${errors} inherited errors (at baseline), ${warnings} warnings.\n` +
  `Target is 0. Every slice that clears some should lower BASELINE.`
)
