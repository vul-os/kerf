// saving-doc.test.js — structural guard for docs/saving-your-work.md
//
// Asserts that the doc file exists and contains the three required section
// headers (L1, L2, L3).  No DOM, no React — pure Node fs reads.

import { describe, it, expect } from 'vitest'
import { readFileSync, existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const DOC_PATH = path.resolve(__dirname, '../../docs/saving-your-work.md')

describe('docs/saving-your-work.md — file exists', () => {
  it('the doc file is present in the repo', () => {
    expect(existsSync(DOC_PATH)).toBe(true)
  })
})

describe('docs/saving-your-work.md — required section headers', () => {
  const body = existsSync(DOC_PATH) ? readFileSync(DOC_PATH, 'utf8') : ''

  it('contains the L1 section (local stash)', () => {
    expect(body).toMatch(/##\s+L1\b/)
  })

  it('contains the L2 section (server autosave)', () => {
    expect(body).toMatch(/##\s+L2\b/)
  })

  it('contains the L3 section (git commit)', () => {
    expect(body).toMatch(/##\s+L3\b/)
  })
})
