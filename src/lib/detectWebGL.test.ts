/**
 * detectWebGL.test.js  — T-C4
 *
 * Unit tests for the centralised detectWebGL helper.
 * All tests patch globalThis.document directly so they work in both Node
 * (no jsdom) and jsdom environments.
 *
 * Coverage:
 *  1.  Returns boolean
 *  2.  SSR / no-document → false
 *  3.  document.createElement throws → false
 *  4.  getContext returns null for all variants → false
 *  5.  Context object has no createBuffer method → false
 *  6.  webgl2 context with createBuffer → true
 *  7.  webgl2 unavailable, webgl1 with createBuffer → true
 *  8.  experimental-webgl fallback → true
 */

import { describe, it, expect, afterEach } from 'vitest'
import { detectWebGL } from './detectWebGL.js'

// Restore helper used inside finally blocks below.
function withDocument(fakeDoc, fn) {
  const orig = globalThis.document
  globalThis.document = fakeDoc
  try {
    return fn()
  } finally {
    globalThis.document = orig
  }
}

describe('detectWebGL', () => {
  it('always returns a boolean', () => {
    expect(typeof detectWebGL()).toBe('boolean')
  })

  it('returns false when document is undefined (SSR / non-DOM)', () => {
    withDocument(undefined, () => {
      expect(detectWebGL()).toBe(false)
    })
  })

  it('returns false when document.createElement throws', () => {
    withDocument(
      { createElement: () => { throw new Error('no canvas support') } },
      () => { expect(detectWebGL()).toBe(false) },
    )
  })

  it('returns false when getContext returns null for all context types', () => {
    withDocument(
      { createElement: () => ({ getContext: () => null }) },
      () => { expect(detectWebGL()).toBe(false) },
    )
  })

  it('returns false when context object has no createBuffer method', () => {
    // A stub context without createBuffer (e.g. a partial mock) is rejected.
    withDocument(
      { createElement: () => ({ getContext: () => ({}) }) },
      () => { expect(detectWebGL()).toBe(false) },
    )
  })

  it('returns true when webgl2 context with createBuffer is available', () => {
    const fakeCtx = { createBuffer: () => {} }
    withDocument(
      {
        createElement: () => ({
          getContext: (type) => (type === 'webgl2' ? fakeCtx : null),
        }),
      },
      () => { expect(detectWebGL()).toBe(true) },
    )
  })

  it('falls back to webgl1 when webgl2 is unavailable', () => {
    const fakeCtx = { createBuffer: () => {} }
    withDocument(
      {
        createElement: () => ({
          getContext: (type) => (type === 'webgl' ? fakeCtx : null),
        }),
      },
      () => { expect(detectWebGL()).toBe(true) },
    )
  })

  it('falls back to experimental-webgl when webgl2 and webgl1 are unavailable', () => {
    const fakeCtx = { createBuffer: () => {} }
    withDocument(
      {
        createElement: () => ({
          getContext: (type) => (type === 'experimental-webgl' ? fakeCtx : null),
        }),
      },
      () => { expect(detectWebGL()).toBe(true) },
    )
  })
})
