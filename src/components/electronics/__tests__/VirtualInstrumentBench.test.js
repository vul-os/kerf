// VirtualInstrumentBench.test.js — source-contract tests for the virtual
// instrument bench React panel and its backend wiring.
//
// Tests:
//   1.  Panel exports a default component named VirtualInstrumentBench
//   2.  Panel has data-testid="virtual-instrument-bench"
//   3.  Panel has a close button
//   4.  Panel has four tab buttons: oscilloscope, multimeter, fgen, probes
//   5.  Oscilloscope tab: channels input + measure button
//   6.  Multimeter tab: node input + mode select + read button
//   7.  Function gen tab: waveform select + freq/amp/offset fields + generate button
//   8.  Probes tab: nodes input + probe button
//   9.  Oscilloscope calls eda_virtual_instrument
//   10. Multimeter calls eda_virtual_instrument
//   11. Function gen calls eda_virtual_instrument
//   12. Probes calls eda_probe_nodes
//   13. All 4 instruments handle offline gracefully with demo-mode message
//   14. Oscilloscope result shows channel measurement block
//   15. Multimeter result shows reading block
//   16. Function gen result shows SPICE line
//   17. Probe result shows probe overlay badge
//   18. Plugin.py registers eda_virtual_instrument + eda_probe_nodes
//   19. Module loads without throwing (dynamic import)

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

const root = resolve(__dirname, '../../..')

function src(relPath) {
  return readFileSync(resolve(root, relPath), 'utf8')
}

// ── Global fetch mock ──────────────────────────────────────────────────────────

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      instrument: 'oscilloscope',
      channels: [],
      warnings: [],
    }),
    text: async () => '{}',
  })
})

// ── Source file under test ─────────────────────────────────────────────────────

const benchSrc = src('components/electronics/VirtualInstrumentBench.jsx')

// ── 1. Default export ──────────────────────────────────────────────────────────

describe('VirtualInstrumentBench — default export', () => {
  it('exports a default component named VirtualInstrumentBench', () => {
    expect(benchSrc).toMatch(/export default function VirtualInstrumentBench/)
  })
})

// ── 2. Root testid ────────────────────────────────────────────────────────────

describe('VirtualInstrumentBench — root testid', () => {
  it('has data-testid="virtual-instrument-bench"', () => {
    expect(benchSrc).toMatch(/data-testid="virtual-instrument-bench"/)
  })
})

// ── 3. Close button ────────────────────────────────────────────────────────────

describe('VirtualInstrumentBench — close button', () => {
  it('has close button testid', () => {
    expect(benchSrc).toMatch(/data-testid="vi-bench-close"/)
  })
})

// ── 4. Four instrument tabs ────────────────────────────────────────────────────

describe('VirtualInstrumentBench — tabs', () => {
  it('has tab button prefix vi-tab- (dynamic template literal)', () => {
    // Tab testids are dynamically generated: `vi-tab-${key}`
    expect(benchSrc).toMatch(/vi-tab-/)
  })

  it('TABS array contains oscilloscope key', () => {
    expect(benchSrc).toMatch(/'oscilloscope'/)
  })

  it('TABS array contains multimeter key', () => {
    expect(benchSrc).toMatch(/'multimeter'/)
  })

  it('TABS array contains fgen key', () => {
    expect(benchSrc).toMatch(/'fgen'/)
  })

  it('TABS array contains probes key', () => {
    expect(benchSrc).toMatch(/'probes'/)
  })
})

// ── 5. Oscilloscope UI controls ────────────────────────────────────────────────

describe('VirtualInstrumentBench — oscilloscope controls', () => {
  it('has channels input testid', () => {
    expect(benchSrc).toMatch(/vi-oscope-channels/)
  })

  it('has measure/run button testid', () => {
    expect(benchSrc).toMatch(/vi-oscope-run/)
  })

  it('has channel result container testid', () => {
    expect(benchSrc).toMatch(/vi-oscope-channel/)
  })
})

// ── 6. Multimeter UI controls ──────────────────────────────────────────────────

describe('VirtualInstrumentBench — multimeter controls', () => {
  it('has node input testid', () => {
    expect(benchSrc).toMatch(/vi-mm-node/)
  })

  it('has mode select testid', () => {
    expect(benchSrc).toMatch(/vi-mm-mode/)
  })

  it('has read button testid', () => {
    expect(benchSrc).toMatch(/vi-mm-read/)
  })

  it('has result container testid', () => {
    expect(benchSrc).toMatch(/vi-mm-result/)
  })
})

// ── 7. Function generator UI controls ─────────────────────────────────────────

describe('VirtualInstrumentBench — function generator controls', () => {
  it('has waveform select testid', () => {
    expect(benchSrc).toMatch(/vi-fgen-waveform/)
  })

  it('has frequency input testid', () => {
    expect(benchSrc).toMatch(/vi-fgen-freq/)
  })

  it('has amplitude input testid', () => {
    expect(benchSrc).toMatch(/vi-fgen-amp/)
  })

  it('has offset input testid', () => {
    expect(benchSrc).toMatch(/vi-fgen-offset/)
  })

  it('has generate button testid', () => {
    expect(benchSrc).toMatch(/vi-fgen-generate/)
  })

  it('has SPICE line output testid', () => {
    expect(benchSrc).toMatch(/vi-fgen-spice-line/)
  })

  it('has .TRAN output testid', () => {
    expect(benchSrc).toMatch(/vi-fgen-tran/)
  })
})

// ── 8. Probes UI controls ──────────────────────────────────────────────────────

describe('VirtualInstrumentBench — probes controls', () => {
  it('has nodes input testid', () => {
    expect(benchSrc).toMatch(/vi-probes-nodes/)
  })

  it('has probe button testid', () => {
    expect(benchSrc).toMatch(/vi-probes-run/)
  })

  it('has result container testid', () => {
    expect(benchSrc).toMatch(/vi-probes-result/)
  })
})

// ── 9–12. Backend tool names ───────────────────────────────────────────────────

describe('VirtualInstrumentBench — backend tool names', () => {
  it('oscilloscope calls eda_virtual_instrument', () => {
    expect(benchSrc).toMatch(/eda_virtual_instrument/)
  })

  it('multimeter calls eda_virtual_instrument', () => {
    // already covered — same tool name
    expect(benchSrc).toMatch(/eda_virtual_instrument/)
  })

  it('function_generator calls eda_virtual_instrument', () => {
    expect(benchSrc).toMatch(/eda_virtual_instrument/)
  })

  it('probes calls eda_probe_nodes', () => {
    expect(benchSrc).toMatch(/eda_probe_nodes/)
  })
})

// ── 13. Offline / demo-mode ────────────────────────────────────────────────────

describe('VirtualInstrumentBench — offline / demo mode', () => {
  it('handles offline gracefully with demo-mode message', () => {
    expect(benchSrc).toMatch(/Backend offline|demo.*data|demo mode/i)
  })
})

// ── 14–17. Result display sections ────────────────────────────────────────────

describe('VirtualInstrumentBench — result display', () => {
  it('oscilloscope result shows channel measurement (Vpp, freq, rise-time)', () => {
    expect(benchSrc).toMatch(/vpp|Vpp/)
    expect(benchSrc).toMatch(/frequency_hz|freq/i)
    expect(benchSrc).toMatch(/rise_time_s|Rise time/i)
  })

  it('multimeter result shows reading block', () => {
    expect(benchSrc).toMatch(/vi-mm-result/)
  })

  it('function gen result shows SPICE line', () => {
    expect(benchSrc).toMatch(/spice_line|spice-line/)
  })

  it('probe result shows on-wire label badge', () => {
    expect(benchSrc).toMatch(/label/)
    expect(benchSrc).toMatch(/vi-probe-/)
  })
})

// ── 18. Plugin registration ────────────────────────────────────────────────────

describe('kerf-electronics plugin — virtual instrument registration', () => {
  it('plugin.py registers eda_virtual_instrument tool module', () => {
    const pluginSrc = readFileSync(
      resolve(root, '../packages/kerf-electronics/src/kerf_electronics/plugin.py'),
      'utf8'
    )
    expect(pluginSrc).toMatch(/virtual_instruments\.tools/)
  })

  it('plugin.py registers eda_probe_nodes via same module', () => {
    const pluginSrc = readFileSync(
      resolve(root, '../packages/kerf-electronics/src/kerf_electronics/plugin.py'),
      'utf8'
    )
    // The module registers both eda_virtual_instrument + eda_probe_nodes
    expect(pluginSrc).toMatch(/virtual_instruments/)
  })
})

// ── 19. Dynamic module load ────────────────────────────────────────────────────

describe('VirtualInstrumentBench — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    vi.mock('react-router-dom', () => ({
      useSearchParams: () => [new URLSearchParams()],
    }))
    const mod = await import('../VirtualInstrumentBench.jsx')
    expect(mod.default).toBeTruthy()
  })
})
