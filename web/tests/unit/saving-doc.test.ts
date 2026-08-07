// saving-doc.test.js — structural guard for docs/save-and-recovery.md
//
// Asserts that the doc file exists and documents all three save layers
// (L1 local stash, L2 server autosave, L3 git commit).  No DOM, no React —
// pure Node fs reads.
//
// This guard used to point at docs/saving-your-work.md, which bfdbd635
// ("docs: full stale-content cleanup") retired in favour of
// docs/save-and-recovery.md without moving the guard — so all four
// assertions failed on every run and the vitest suite carried a permanent
// red. Retargeted at the successor doc rather than deleted: the thing worth
// guarding is that the three layers stay documented, and they are.

import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DOC_PATH = path.resolve(__dirname, '../../../docs/save-and-recovery.md')

describe('docs/save-and-recovery.md — file exists', () => {
  it('the doc file is present in the repo', () => {
    expect(existsSync(DOC_PATH)).toBe(true)
  })
})

describe('docs/save-and-recovery.md — required section headers', () => {
  const body = existsSync(DOC_PATH) ? readFileSync(DOC_PATH, 'utf8') : ''

  it('contains the L1 section (local stash)', () => {
    expect(body).toMatch(/#{2,3}\s+L1\b/)
  })

  it('contains the L2 section (server autosave)', () => {
    expect(body).toMatch(/#{2,3}\s+L2\b/)
  })

  it('contains the L3 section (git commit)', () => {
    expect(body).toMatch(/#{2,3}\s+L3\b/)
  })
})
