/**
 * motion.test.js — panel registry fragment for motion_study
 *
 * Tests
 * -----
 * 1. Default export is an array.
 * 2. Contains exactly one entry.
 * 3. Entry id is 'motion_study'.
 * 4. Entry kinds includes 'motion_study'.
 * 5. Entry exts includes '.motion'.
 * 6. Entry load is a function.
 * 7. Entry label is defined.
 * 8. load() returns a promise (lazy import shape).
 * 9. No duplicate ids in the export.
 */

import { describe, it, expect } from 'vitest'
import entries from './motion.js'

describe('motion panel registry fragment', () => {
  it('default export is an array', () => {
    expect(Array.isArray(entries)).toBe(true)
  })

  it('contains exactly one entry', () => {
    expect(entries).toHaveLength(1)
  })

  it('entry id is motion_study', () => {
    expect(entries[0].id).toBe('motion_study')
  })

  it('entry kinds includes motion_study', () => {
    expect(entries[0].kinds).toContain('motion_study')
  })

  it('entry exts includes .motion', () => {
    expect(entries[0].exts).toContain('.motion')
  })

  it('entry load is a function', () => {
    expect(typeof entries[0].load).toBe('function')
  })

  it('entry label is defined and non-empty', () => {
    expect(entries[0].label).toBeTruthy()
  })

  it('load() returns a thenable that resolves to a module with a default export', async () => {
    // AssemblyMotionStudioPanel.jsx (the module behind this entry) imports
    // only react/lucide-react/zustand — no Three.js — so awaiting it here is
    // cheap. This used to fire the import and NOT await it ("to avoid
    // loading Three.js"), but that left the dynamic import in flight after
    // the test (and its vitest environment) finished; when it settled later
    // it surfaced as an "EnvironmentTeardownError" unhandled rejection that
    // fails the overall `vitest run` exit code even though every test
    // passes. Awaiting it lets it settle inside the test's own lifetime.
    const result = entries[0].load()
    expect(typeof result.then).toBe('function')
    const mod = await result
    expect(typeof mod.default).toBe('function')
  })

  it('no duplicate ids', () => {
    const ids = entries.map((e) => e.id)
    const unique = new Set(ids)
    expect(unique.size).toBe(ids.length)
  })
})
