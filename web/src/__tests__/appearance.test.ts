import { describe, it, expect } from 'vitest'
import {
  parseAppearance,
  writeAppearance,
  stripAppearance,
  mergeAppearance,
  normalizeHex,
  hexToInt,
  intToHex,
} from '../lib/appearance.js'

const SRC = `export default function ({ primitives }) {
  return [{ id: 'body', geom: primitives.cuboid({ size: [20, 20, 20] }) }]
}`

describe('appearance marker round-trip', () => {
  it('writes a marker and reads it back unchanged', () => {
    const written = writeAppearance(SRC, {
      body: { color: '#6b9bc9', opacity: 0.45, material: '6061-T6' },
    })
    expect(written.split('\n')[0]).toContain('// kerf:appearance=')
    expect(parseAppearance(written)).toEqual({
      body: { color: '#6b9bc9', opacity: 0.45, material: '6061-T6' },
    })
  })

  it('leaves the original source intact below the marker', () => {
    const written = writeAppearance(SRC, { body: { color: '#ffffff' } })
    expect(written.split('\n').slice(1).join('\n')).toBe(SRC)
  })

  it('replaces an existing marker rather than stacking them', () => {
    const once = writeAppearance(SRC, { body: { color: '#111111' } })
    const twice = writeAppearance(once, { body: { color: '#222222' } })
    const markers = twice.split('\n').filter((l) => l.startsWith('// kerf:appearance='))
    expect(markers).toHaveLength(1)
    expect(parseAppearance(twice)).toEqual({ body: { color: '#222222' } })
  })

  it('removes the marker entirely when no overrides remain', () => {
    const written = writeAppearance(SRC, { body: { color: '#111111' } })
    expect(writeAppearance(written, {})).toBe(SRC)
  })

  it('returns {} for a file with no marker', () => {
    expect(parseAppearance(SRC)).toEqual({})
  })

  it('degrades to {} on a mangled marker instead of throwing', () => {
    const broken = `// kerf:appearance={"body":{"color":\n${SRC}`
    expect(() => parseAppearance(broken)).not.toThrow()
    expect(parseAppearance(broken)).toEqual({})
  })

  it('ignores unknown keys and out-of-range values', () => {
    const written = writeAppearance(SRC, {
      body: { color: 'not-a-colour', opacity: 5, evil: 'drop me', roughness: 0.3 },
    })
    // color is invalid → dropped; opacity clamps to 1 → not an override, so not
    // persisted; `evil` is not a known field. Only roughness survives.
    expect(parseAppearance(written)).toEqual({ body: { roughness: 0.3 } })
  })
})

describe('opacity normalisation', () => {
  it('does not persist a fully-opaque override (1 is the default)', () => {
    const written = writeAppearance(SRC, { body: { opacity: 1 } })
    // opacity:1 alone is not an override, so the entry — and the marker — go away
    expect(written).toBe(SRC)
  })

  it('clamps opacity into 0..1', () => {
    const written = writeAppearance(SRC, { body: { opacity: -3, color: '#abcdef' } })
    expect(parseAppearance(written).body.opacity).toBe(0)
  })
})

describe('stripAppearance', () => {
  // The editor compares STRIPPED sources to decide whether to re-run JSCAD.
  // If a marker-only edit doesn't strip to the same string, the model re-runs,
  // every mesh is rebuilt, and the viewport visibly flashes on each colour tweak.
  it('makes a marker-only edit indistinguishable from the original', () => {
    const a = writeAppearance(SRC, { body: { color: '#111111' } })
    const b = writeAppearance(SRC, { body: { color: '#222222', opacity: 0.5 } })
    expect(stripAppearance(a)).toBe(SRC)
    expect(stripAppearance(a)).toBe(stripAppearance(b))
  })

  it('leaves a source with no marker untouched', () => {
    expect(stripAppearance(SRC)).toBe(SRC)
  })

  it('still sees a real code edit', () => {
    const withMarker = writeAppearance(SRC, { body: { color: '#111111' } })
    const edited = writeAppearance(SRC.replace('20, 20, 20', '30, 30, 30'), {
      body: { color: '#111111' },
    })
    expect(stripAppearance(edited)).not.toBe(stripAppearance(withMarker))
  })
})

describe('mergeAppearance', () => {
  it('merges a patch into one part without touching the others', () => {
    const before = { a: { color: '#111111' }, b: { opacity: 0.5 } }
    const after = mergeAppearance(before, 'a', { opacity: 0.25 })
    expect(after).toEqual({ a: { color: '#111111', opacity: 0.25 }, b: { opacity: 0.5 } })
  })

  it('clears a single field when passed null', () => {
    const before = { a: { color: '#111111', opacity: 0.25 } }
    expect(mergeAppearance(before, 'a', { color: null })).toEqual({ a: { opacity: 0.25 } })
  })

  it('drops the entry once its last field is cleared', () => {
    const before = { a: { color: '#111111' }, b: { opacity: 0.5 } }
    expect(mergeAppearance(before, 'a', { color: null })).toEqual({ b: { opacity: 0.5 } })
  })
})

describe('colour helpers', () => {
  it('expands shorthand hex and normalises case', () => {
    expect(normalizeHex('#ABC')).toBe('#aabbcc')
    expect(normalizeHex('6B9BC9')).toBe('#6b9bc9')
    expect(normalizeHex('nope')).toBeNull()
  })

  it('round-trips hex ↔ int', () => {
    expect(hexToInt('#6b9bc9')).toBe(0x6b9bc9)
    expect(intToHex(0x6b9bc9)).toBe('#6b9bc9')
    expect(intToHex(0x000000)).toBe('#000000')
  })
})
