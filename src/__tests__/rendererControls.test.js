// Slice 7: the scattered floating viewport toggles (Zebra / Bloom /
// HDRI) are consolidated into one Render dropdown, a Daylight mode is
// added, and the exposure slider is a standalone, relabelled, icon'd
// control. @testing-library/react isn't available here, and the controls
// are gated behind viewport/menu state, so this pins the contract at the
// source level (same approach as the other UI-wiring regressions).

import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'
import { describe, it, expect } from 'vitest'

const root = join(dirname(fileURLToPath(import.meta.url)), '..')
const src = readFileSync(join(root, 'components/Renderer.jsx'), 'utf8')

describe('3D render controls', () => {
  it('exposes a Daylight lighting mode + state', () => {
    expect(src).toContain('const [daylight, setDaylight] = useState(false)')
    // The lighting effect drives the key/ambient/fill rig.
    expect(src).toContain('}, [daylight])')
    expect(src).toMatch(/s\.key\.intensity = 4\.4/)
  })

  it('consolidates the toggles into one Render dropdown', () => {
    expect(src).toContain('const [renderMenuOpen, setRenderMenuOpen] = useState(false)')
    expect(src).toContain('Render mode')
    // All four options live in the menu.
    for (const label of ['Daylight', 'Zebra', 'Bloom', 'HDRI background']) {
      expect(src).toContain(`label: '${label}'`)
    }
  })

  it('removes the old scattered standalone toggle buttons', () => {
    // The old absolute top-3 Zebra button and the top-12 Bloom/HDRI
    // column are gone (their toggles now live in the dropdown).
    expect(src).not.toContain('Toggle zebra / reflection lines (Class-A surface analysis)')
    expect(src).not.toContain('>HDRI bg<')
    expect(src).not.toContain('absolute top-12 right-3 z-10 flex flex-col')
  })

  it('exposure slider is standalone, relabelled, with a Sun icon', () => {
    expect(src).toContain("import { Sun, SlidersHorizontal, Check, ChevronDown, MonitorX, Layers } from 'lucide-react'")
    expect(src).toContain('>\n          Exposure\n        </label>')
    expect(src).toContain('id="kerf-exposure-slider"')
  })
})
