// EDAParityPanels.test.js — Vitest source-contract tests for EDA parity panel components.
//
// Tests:
//   1. DrcErcPanel source contracts (endpoints, testids)
//   2. SIPanel source contracts (endpoints, IBIS, testids)
//   3. SiliconSynthPanel source contracts (OpenLane endpoint, graceful pending, testids)
//   4. PCBInteractiveEditor imports all three panels
//   5. Toolbar has three panel toggle buttons
//   6. PCBInteractiveEditor source references showDrcPanel / showSIPanel / showSiliconPanel state
//   7. DrcErcPanel module loads without throwing (dynamic import)
//   8. SIPanel module loads without throwing (dynamic import)
//   9. SiliconSynthPanel module loads without throwing (dynamic import)

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// ── Global fetch mock ──────────────────────────────────────────────────────────

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true,
      violations: [],
      errors: [],
      warnings: [],
      result: { z0_ohms: 50.0, td_ps_per_mm: 180.0, flight_time_ps: 9000.0 },
    }),
    text: async () => '{}',
  })
})

// ── Helpers ───────────────────────────────────────────────────────────────────

const root = resolve(__dirname, '../../..')

function src(relPath) {
  return readFileSync(resolve(root, relPath), 'utf8')
}

// ── 1. DrcErcPanel source contracts ──────────────────────────────────────────

describe('DrcErcPanel — source contracts', () => {
  const panelSrc = src('components/electronics/DrcErcPanel.jsx')

  it('exports a default component named DrcErcPanel', () => {
    expect(panelSrc).toMatch(/export default function DrcErcPanel/)
  })

  it('calls run_pcb_drc endpoint', () => {
    expect(panelSrc).toMatch(/run_pcb_drc/)
  })

  it('calls run_erc endpoint', () => {
    expect(panelSrc).toMatch(/run_erc/)
  })

  it('has data-testid="drc-erc-panel"', () => {
    expect(panelSrc).toMatch(/data-testid="drc-erc-panel"/)
  })

  it('has DRC/ERC tabs via dynamic testid', () => {
    // Tab testids are generated as `drc-erc-tab-${key}` from the 'drc'/'erc' keys
    expect(panelSrc).toMatch(/drc-erc-tab/)
  })

  it('renders drc and erc tab keys', () => {
    expect(panelSrc).toMatch(/'drc'/)
    expect(panelSrc).toMatch(/'erc'/)
  })

  it('has refresh button', () => {
    expect(panelSrc).toMatch(/data-testid="drc-erc-refresh"/)
  })

  it('has close button', () => {
    expect(panelSrc).toMatch(/data-testid="drc-erc-close"/)
  })

  it('shows violations list', () => {
    expect(panelSrc).toMatch(/data-testid="drc-erc-list"/)
  })

  it('handles offline gracefully with demo data', () => {
    expect(panelSrc).toMatch(/demo.*mode|Backend offline/i)
  })
})

// ── 2. SIPanel source contracts ───────────────────────────────────────────────

describe('SIPanel — source contracts', () => {
  const panelSrc = src('components/electronics/SIPanel.jsx')

  it('exports a default component named SIPanel', () => {
    expect(panelSrc).toMatch(/export default function SIPanel/)
  })

  it('calls si_report endpoint', () => {
    expect(panelSrc).toMatch(/si_report/)
  })

  it('calls si_ibis_parse endpoint', () => {
    expect(panelSrc).toMatch(/si_ibis_parse/)
  })

  it('calls si_ibis_channel_response endpoint', () => {
    expect(panelSrc).toMatch(/si_ibis_channel_response/)
  })

  it('has data-testid="si-panel"', () => {
    expect(panelSrc).toMatch(/data-testid="si-panel"/)
  })

  it('has SI Z0/delay tab via dynamic testid', () => {
    // Tab testids are `si-tab-${key}` from 'si'/'ibis' keys
    expect(panelSrc).toMatch(/si-tab/)
  })

  it('renders si and ibis tab keys', () => {
    expect(panelSrc).toMatch(/'si'/)
    expect(panelSrc).toMatch(/'ibis'/)
  })

  it('has structure selector testId', () => {
    expect(panelSrc).toMatch(/si-structure/)
  })

  it('has run button', () => {
    expect(panelSrc).toMatch(/data-testid="si-run-btn"/)
  })

  it('has IBIS text input', () => {
    expect(panelSrc).toMatch(/data-testid="ibis-text-input"/)
  })

  it('has IBIS run button', () => {
    expect(panelSrc).toMatch(/data-testid="ibis-run-btn"/)
  })

  it('shows results section', () => {
    expect(panelSrc).toMatch(/data-testid="si-results"/)
  })

  it('references IPC-2141A standard', () => {
    expect(panelSrc).toMatch(/IPC-2141A/)
  })
})

// ── 3. SiliconSynthPanel source contracts ─────────────────────────────────────

describe('SiliconSynthPanel — source contracts', () => {
  const panelSrc = src('components/electronics/SiliconSynthPanel.jsx')

  it('exports a default component named SiliconSynthPanel', () => {
    expect(panelSrc).toMatch(/export default function SiliconSynthPanel/)
  })

  it('calls silicon_run_openlane endpoint', () => {
    expect(panelSrc).toMatch(/silicon_run_openlane/)
  })

  it('has data-testid="silicon-synth-panel"', () => {
    expect(panelSrc).toMatch(/data-testid="silicon-synth-panel"/)
  })

  it('has design name input', () => {
    expect(panelSrc).toMatch(/data-testid="synth-design-name"/)
  })

  it('has PDK selector', () => {
    expect(panelSrc).toMatch(/data-testid="synth-pdk"/)
  })

  it('has clock period input', () => {
    expect(panelSrc).toMatch(/data-testid="synth-clock-period"/)
  })

  it('has Verilog text area', () => {
    expect(panelSrc).toMatch(/data-testid="synth-verilog"/)
  })

  it('has run button', () => {
    expect(panelSrc).toMatch(/data-testid="synth-run-btn"/)
  })

  it('has result display', () => {
    expect(panelSrc).toMatch(/data-testid="synth-result"/)
  })

  it('gracefully handles pending status (OpenLane not installed)', () => {
    expect(panelSrc).toMatch(/pending/)
    expect(panelSrc).toMatch(/synth-status-pending/)
  })

  it('supports sky130A PDK', () => {
    expect(panelSrc).toMatch(/sky130A/)
  })

  it('references Yosys and OpenLane', () => {
    expect(panelSrc).toMatch(/Yosys|OpenLane/)
  })
})

// ── 4. PCBInteractiveEditor — imports all three panels ────────────────────────

describe('PCBInteractiveEditor — panel imports and state', () => {
  const editorSrc = src('components/electronics/PCBInteractiveEditor.jsx')

  it('imports DrcErcPanel', () => {
    expect(editorSrc).toMatch(/import.*DrcErcPanel/)
  })

  it('imports SIPanel', () => {
    expect(editorSrc).toMatch(/import.*SIPanel/)
  })

  it('imports SiliconSynthPanel', () => {
    expect(editorSrc).toMatch(/import.*SiliconSynthPanel/)
  })

  it('has showDrcPanel state', () => {
    expect(editorSrc).toMatch(/showDrcPanel/)
  })

  it('has showSIPanel state', () => {
    expect(editorSrc).toMatch(/showSIPanel/)
  })

  it('has showSiliconPanel state', () => {
    expect(editorSrc).toMatch(/showSiliconPanel/)
  })

  it('renders DrcErcPanel conditionally', () => {
    expect(editorSrc).toMatch(/<DrcErcPanel/)
  })

  it('renders SIPanel conditionally', () => {
    expect(editorSrc).toMatch(/<SIPanel/)
  })

  it('renders SiliconSynthPanel conditionally', () => {
    expect(editorSrc).toMatch(/<SiliconSynthPanel/)
  })

  it('passes onToggleDrcPanel to Toolbar', () => {
    expect(editorSrc).toMatch(/onToggleDrcPanel/)
  })

  it('passes onToggleSIPanel to Toolbar', () => {
    expect(editorSrc).toMatch(/onToggleSIPanel/)
  })

  it('passes onToggleSiliconPanel to Toolbar', () => {
    expect(editorSrc).toMatch(/onToggleSiliconPanel/)
  })
})

// ── 5. Toolbar — panel toggle buttons ────────────────────────────────────────

describe('Toolbar — panel toggle buttons', () => {
  const toolbarSrc = src('components/electronics/pcb-editor/Toolbar.jsx')

  it('has DRC/ERC panel toggle button', () => {
    expect(toolbarSrc).toMatch(/btn-toggle-drc-panel/)
  })

  it('has SI panel toggle button', () => {
    expect(toolbarSrc).toMatch(/btn-toggle-si-panel/)
  })

  it('has Silicon synth panel toggle button', () => {
    expect(toolbarSrc).toMatch(/btn-toggle-silicon-panel/)
  })

  it('accepts onToggleDrcPanel prop', () => {
    expect(toolbarSrc).toMatch(/onToggleDrcPanel/)
  })

  it('accepts onToggleSIPanel prop', () => {
    expect(toolbarSrc).toMatch(/onToggleSIPanel/)
  })

  it('accepts onToggleSiliconPanel prop', () => {
    expect(toolbarSrc).toMatch(/onToggleSiliconPanel/)
  })
})

// ── 6. Plugin registration — si_ibis in tool_modules ─────────────────────────

describe('kerf-electronics plugin — si_ibis registration', () => {
  it('plugin.py contains si_ibis in tool_modules', () => {
    const pluginSrc = readFileSync(
      resolve(root, '../packages/kerf-electronics/src/kerf_electronics/plugin.py'),
      'utf8'
    )
    expect(pluginSrc).toMatch(/kerf_electronics\.tools\.si_ibis/)
  })
})

// ── 7-9. Dynamic module load tests ───────────────────────────────────────────

describe('DrcErcPanel — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    vi.mock('react-router-dom', () => ({
      useSearchParams: () => [new URLSearchParams()],
    }))
    const mod = await import('../DrcErcPanel.jsx')
    expect(mod.default).toBeTruthy()
  })
})

describe('SIPanel — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    const mod = await import('../SIPanel.jsx')
    expect(mod.default).toBeTruthy()
  })
})

describe('SiliconSynthPanel — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    const mod = await import('../SiliconSynthPanel.jsx')
    expect(mod.default).toBeTruthy()
  })
})
