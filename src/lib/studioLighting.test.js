import { describe, it, expect } from 'vitest'
import {
  STUDIO_PRESETS,
  buildThreePointPreset,
  buildFourPointPreset,
  buildButterflyPreset,
  buildRembrandtPreset,
  buildRingLightPreset,
  buildSoftboxPreset,
  applyStudioPreset,
} from './studioLighting.js'

const TARGET = [0, 0, 500]

// ── STUDIO_PRESETS list ────────────────────────────────────────────────────────

describe('STUDIO_PRESETS', () => {
  it('contains exactly 6 presets', () => {
    expect(STUDIO_PRESETS).toHaveLength(6)
  })

  it('includes all expected preset names', () => {
    expect(STUDIO_PRESETS).toContain('three-point')
    expect(STUDIO_PRESETS).toContain('four-point')
    expect(STUDIO_PRESETS).toContain('butterfly')
    expect(STUDIO_PRESETS).toContain('rembrandt')
    expect(STUDIO_PRESETS).toContain('ring-light')
    expect(STUDIO_PRESETS).toContain('softbox')
  })
})

// ── three-point ────────────────────────────────────────────────────────────────

describe('buildThreePointPreset', () => {
  it('returns exactly 3 lights', () => {
    expect(buildThreePointPreset(TARGET)).toHaveLength(3)
  })

  it('has key, fill, and back lights', () => {
    const ids = buildThreePointPreset(TARGET).map((l) => l.id)
    expect(ids).toContain('key')
    expect(ids).toContain('fill')
    expect(ids).toContain('back')
  })

  it('key is a sun light', () => {
    const key = buildThreePointPreset(TARGET).find((l) => l.id === 'key')
    expect(key.kind).toBe('sun')
  })

  it('fill is an area light', () => {
    const fill = buildThreePointPreset(TARGET).find((l) => l.id === 'fill')
    expect(fill.kind).toBe('area')
  })
})

// ── four-point ─────────────────────────────────────────────────────────────────

describe('buildFourPointPreset', () => {
  it('returns exactly 4 lights', () => {
    expect(buildFourPointPreset(TARGET)).toHaveLength(4)
  })

  it('includes the kicker light', () => {
    const ids = buildFourPointPreset(TARGET).map((l) => l.id)
    expect(ids).toContain('kicker')
  })

  it('kicker is a sun light', () => {
    const kicker = buildFourPointPreset(TARGET).find((l) => l.id === 'kicker')
    expect(kicker.kind).toBe('sun')
  })

  it('includes all three-point lights plus kicker', () => {
    const ids = buildFourPointPreset(TARGET).map((l) => l.id)
    expect(ids).toContain('key')
    expect(ids).toContain('fill')
    expect(ids).toContain('back')
    expect(ids).toContain('kicker')
  })
})

// ── butterfly ──────────────────────────────────────────────────────────────────

describe('buildButterflyPreset', () => {
  it('returns exactly 2 lights', () => {
    expect(buildButterflyPreset(TARGET)).toHaveLength(2)
  })

  it('has butterfly-key and butterfly-fill', () => {
    const ids = buildButterflyPreset(TARGET).map((l) => l.id)
    expect(ids).toContain('butterfly-key')
    expect(ids).toContain('butterfly-fill')
  })

  it('key is a sun light', () => {
    const key = buildButterflyPreset(TARGET).find((l) => l.id === 'butterfly-key')
    expect(key.kind).toBe('sun')
  })

  it('fill is an area light with size_mm', () => {
    const fill = buildButterflyPreset(TARGET).find((l) => l.id === 'butterfly-fill')
    expect(fill.kind).toBe('area')
    expect(fill.size_mm).toBeGreaterThan(0)
  })
})

// ── rembrandt ──────────────────────────────────────────────────────────────────

describe('buildRembrandtPreset', () => {
  it('returns exactly 2 lights', () => {
    expect(buildRembrandtPreset(TARGET)).toHaveLength(2)
  })

  it('has rembrandt-key and rembrandt-fill', () => {
    const ids = buildRembrandtPreset(TARGET).map((l) => l.id)
    expect(ids).toContain('rembrandt-key')
    expect(ids).toContain('rembrandt-fill')
  })

  it('key is a sun light', () => {
    const key = buildRembrandtPreset(TARGET).find((l) => l.id === 'rembrandt-key')
    expect(key.kind).toBe('sun')
  })

  it('fill is an area light', () => {
    const fill = buildRembrandtPreset(TARGET).find((l) => l.id === 'rembrandt-fill')
    expect(fill.kind).toBe('area')
  })
})

// ── ring-light ─────────────────────────────────────────────────────────────────

describe('buildRingLightPreset', () => {
  it('returns exactly 8 lights', () => {
    expect(buildRingLightPreset(TARGET)).toHaveLength(8)
  })

  it('all lights are sun kind', () => {
    buildRingLightPreset(TARGET).forEach((l) => {
      expect(l.kind).toBe('sun')
    })
  })

  it('lights are named ring-0 through ring-7', () => {
    const ids = buildRingLightPreset(TARGET).map((l) => l.id)
    for (let i = 0; i < 8; i++) {
      expect(ids).toContain(`ring-${i}`)
    }
  })

  it('angular spacing between consecutive lights is 2π/8 to within 1e-9', () => {
    const lights = buildRingLightPreset(TARGET)
    const expectedStep = (2 * Math.PI) / 8

    // Extract the xy-plane angle from each direction vector
    const angles = lights.map((l) => Math.atan2(-l.direction[1], -l.direction[0]))

    // Sort angles so we can measure consecutive gaps
    const sorted = [...angles].sort((a, b) => a - b)

    for (let i = 0; i < sorted.length; i++) {
      const next = sorted[(i + 1) % sorted.length]
      const prev = sorted[i]
      let gap = next - prev
      // Wrap around 2π for the last segment
      if (gap < 0) gap += 2 * Math.PI
      expect(Math.abs(gap - expectedStep)).toBeLessThan(1e-9)
    }
  })

  it('all lights have the same elevation (direction z-component)', () => {
    const lights = buildRingLightPreset(TARGET)
    const dz0 = lights[0].direction[2]
    lights.forEach((l) => {
      expect(Math.abs(l.direction[2] - dz0)).toBeLessThan(1e-10)
    })
  })
})

// ── softbox ────────────────────────────────────────────────────────────────────

describe('buildSoftboxPreset', () => {
  it('returns exactly 1 light', () => {
    expect(buildSoftboxPreset(TARGET)).toHaveLength(1)
  })

  it('the light is an area kind', () => {
    expect(buildSoftboxPreset(TARGET)[0].kind).toBe('area')
  })

  it('has size_mm = 1500', () => {
    expect(buildSoftboxPreset(TARGET)[0].size_mm).toBe(1500)
  })

  it('has a position array', () => {
    const light = buildSoftboxPreset(TARGET)[0]
    expect(Array.isArray(light.position)).toBe(true)
    expect(light.position).toHaveLength(3)
  })
})

// ── applyStudioPreset ─────────────────────────────────────────────────────────

describe('applyStudioPreset', () => {
  const baseDoc = {
    version: 1,
    name: 'Test',
    scene_file_id: 'file-abc',
    camera: { position: [0, 0, 0], target: [0, 0, 0], fov_deg: 45, type: 'perspective' },
    lights: [{ id: 'old', kind: 'sun', direction: [0, 0, -1], intensity: 1, color: '#fff' }],
    render_settings: { resolution: [1920, 1080], samples: 64, output_format: 'png', denoise: true },
  }

  it('returns a NEW doc object (immutability)', () => {
    const next = applyStudioPreset(baseDoc, 'three-point')
    expect(next).not.toBe(baseDoc)
  })

  it('does not mutate the original lights array', () => {
    const origLen = baseDoc.lights.length
    applyStudioPreset(baseDoc, 'three-point')
    expect(baseDoc.lights).toHaveLength(origLen)
  })

  it('three-point produces 3 lights', () => {
    expect(applyStudioPreset(baseDoc, 'three-point').lights).toHaveLength(3)
  })

  it('four-point produces 4 lights', () => {
    expect(applyStudioPreset(baseDoc, 'four-point').lights).toHaveLength(4)
  })

  it('butterfly produces 2 lights', () => {
    expect(applyStudioPreset(baseDoc, 'butterfly').lights).toHaveLength(2)
  })

  it('rembrandt produces 2 lights', () => {
    expect(applyStudioPreset(baseDoc, 'rembrandt').lights).toHaveLength(2)
  })

  it('ring-light produces 8 lights', () => {
    expect(applyStudioPreset(baseDoc, 'ring-light').lights).toHaveLength(8)
  })

  it('softbox produces 1 light', () => {
    expect(applyStudioPreset(baseDoc, 'softbox').lights).toHaveLength(1)
  })

  it('preserves other doc fields unchanged', () => {
    const next = applyStudioPreset(baseDoc, 'softbox')
    expect(next.version).toBe(baseDoc.version)
    expect(next.scene_file_id).toBe(baseDoc.scene_file_id)
    expect(next.camera).toBe(baseDoc.camera)
  })

  it('throws for an unknown preset name', () => {
    expect(() => applyStudioPreset(baseDoc, 'neon-disco')).toThrow(/neon-disco/)
  })

  it('accepts a custom target', () => {
    const next = applyStudioPreset(baseDoc, 'three-point', [100, 200, 300])
    const fill = next.lights.find((l) => l.id === 'fill')
    // fill position should be offset from [100, 200, 300]
    expect(fill.position[0]).toBeCloseTo(100 + 3000, 0)
  })
})
