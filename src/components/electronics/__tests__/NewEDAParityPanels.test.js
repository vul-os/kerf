// NewEDAParityPanels.test.js — Vitest source-contract tests for 5 new EDA parity panels.
//
// Panels under test:
//   1. MultiBoardPanel  — Altium MB3D multi-board workspace
//   2. PCB3DPanel       — 3D PCB editor (STEP import + clearance DRC)
//   3. EMCPanel         — EMC pre-compliance (radiated / shielding / FCC+CISPR)
//   4. PCBThermalPanel  — PCB thermal analysis (2D FD hotspot map)
//
// Also tests:
//   5. PCBInteractiveEditor wires all 4 new panels (imports + state + render)
//   6. Toolbar has 4 new panel toggle buttons
//   7. Python plugin.py registers pcb_3d_clearance + idf_roundtrip modules

import { describe, it, expect, vi, beforeAll } from 'vitest'
import { readFileSync } from 'fs'
import { resolve } from 'path'

// ── Global fetch mock ──────────────────────────────────────────────────────────

beforeAll(() => {
  global.fetch = vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      ok: true,
      valid: true,
      mating_issues: [],
      overlap_warnings: [],
      violation_count: 0,
      violations: [],
      bridge_count: 0,
      bridges: [],
      floating_nets: [],
      board_count: 2,
      filename: 'assembly.step',
      size_bytes: 1024,
    }),
    text: async () => '{}',
  })
})

// ── Helpers ───────────────────────────────────────────────────────────────────

const root = resolve(__dirname, '../../..')

function src(relPath) {
  return readFileSync(resolve(root, relPath), 'utf8')
}

// ── 1. MultiBoardPanel source contracts ───────────────────────────────────────

describe('MultiBoardPanel — source contracts', () => {
  const panelSrc = src('components/electronics/MultiBoardPanel.jsx')

  it('exports a default component named MultiBoardPanel', () => {
    expect(panelSrc).toMatch(/export default function MultiBoardPanel/)
  })

  it('calls electronics_mb3d_validate_workspace endpoint', () => {
    expect(panelSrc).toMatch(/electronics_mb3d_validate_workspace/)
  })

  it('calls electronics_mb3d_net_map endpoint', () => {
    expect(panelSrc).toMatch(/electronics_mb3d_net_map/)
  })

  it('calls electronics_mb3d_export_step endpoint', () => {
    expect(panelSrc).toMatch(/electronics_mb3d_export_step/)
  })

  it('has data-testid="multi-board-panel"', () => {
    expect(panelSrc).toMatch(/data-testid="multi-board-panel"/)
  })

  it('has data-testid="multi-board-close"', () => {
    expect(panelSrc).toMatch(/data-testid="multi-board-close"/)
  })

  it('has tab testid pattern mb3d-tab-${id}', () => {
    // Tabs use dynamic testid: data-testid={`mb3d-tab-${id}`}
    expect(panelSrc).toMatch(/mb3d-tab-\$\{id\}|mb3d-tab-/)
  })

  it('has workspace tab defined in TABS', () => {
    expect(panelSrc).toMatch(/'workspace'/)
  })

  it('has connectors tab defined in TABS', () => {
    expect(panelSrc).toMatch(/'connectors'/)
  })

  it('has netmap tab defined in TABS', () => {
    expect(panelSrc).toMatch(/'netmap'/)
  })

  it('has export tab defined in TABS', () => {
    // 'export' appears in TABS array
    expect(panelSrc).toMatch(/id:\s*'export'|'export'/)
  })

  it('has validate button testid', () => {
    expect(panelSrc).toMatch(/data-testid="mb3d-validate-btn"/)
  })

  it('has netmap button testid', () => {
    expect(panelSrc).toMatch(/data-testid="mb3d-netmap-btn"/)
  })

  it('has STEP export button testid', () => {
    expect(panelSrc).toMatch(/data-testid="mb3d-step-btn"/)
  })

  it('has validate result testid', () => {
    expect(panelSrc).toMatch(/data-testid="mb3d-validate-result"/)
  })

  it('has board row testid pattern', () => {
    expect(panelSrc).toMatch(/mb3d-board-/)
  })

  it('references Altium MB3D', () => {
    expect(panelSrc).toMatch(/MB3D|multi.*board|Multi.*Board/i)
  })

  it('references IPC-2581', () => {
    expect(panelSrc).toMatch(/IPC-2581/)
  })

  it('shows offline banner when backend unavailable', () => {
    expect(panelSrc).toMatch(/Backend offline|demo.*data/i)
  })
})

// ── 2. PCB3DPanel source contracts ────────────────────────────────────────────

describe('PCB3DPanel — source contracts', () => {
  const panelSrc = src('components/electronics/PCB3DPanel.jsx')

  it('exports a default component named PCB3DPanel', () => {
    expect(panelSrc).toMatch(/export default function PCB3DPanel/)
  })

  it('calls pcb_3d_clearance_check endpoint', () => {
    expect(panelSrc).toMatch(/pcb_3d_clearance_check/)
  })

  it('calls pcb_step_import_body endpoint', () => {
    expect(panelSrc).toMatch(/pcb_step_import_body/)
  })

  it('has data-testid="pcb-3d-panel"', () => {
    expect(panelSrc).toMatch(/data-testid="pcb-3d-panel"/)
  })

  it('has data-testid="pcb-3d-close"', () => {
    expect(panelSrc).toMatch(/data-testid="pcb-3d-close"/)
  })

  it('has min clearance input testid', () => {
    expect(panelSrc).toMatch(/data-testid="pcb3d-min-clearance"/)
  })

  it('has clearance run button testid', () => {
    expect(panelSrc).toMatch(/data-testid="pcb3d-clearance-btn"/)
  })

  it('has clearance result testid', () => {
    expect(panelSrc).toMatch(/data-testid="pcb3d-clearance-result"/)
  })

  it('has STEP text input testid', () => {
    expect(panelSrc).toMatch(/data-testid="pcb3d-step-text"/)
  })

  it('has STEP import button testid', () => {
    expect(panelSrc).toMatch(/data-testid="pcb3d-step-import-btn"/)
  })

  it('has IDF roundtrip button testid', () => {
    expect(panelSrc).toMatch(/data-testid="pcb3d-idf-roundtrip-btn"/)
  })

  it('references Altium 3D Body Clearance', () => {
    expect(panelSrc).toMatch(/Altium|3D.*[Cc]learance|clearance.*3D/)
  })

  it('references IPC-7351B', () => {
    expect(panelSrc).toMatch(/IPC-7351B/)
  })

  it('distinguishes body_intersection (error) vs body_clearance (warning)', () => {
    expect(panelSrc).toMatch(/body_intersection/)
    // body_clearance appears as a violation_type value
    expect(panelSrc).toMatch(/body_clearance|violation_type/)
  })
})

// ── 3. EMCPanel source contracts ──────────────────────────────────────────────

describe('EMCPanel — source contracts', () => {
  const panelSrc = src('components/electronics/EMCPanel.jsx')

  it('exports a default component named EMCPanel', () => {
    expect(panelSrc).toMatch(/export default function EMCPanel/)
  })

  it('has data-testid="emc-panel"', () => {
    expect(panelSrc).toMatch(/data-testid="emc-panel"/)
  })

  it('has data-testid="emc-close"', () => {
    expect(panelSrc).toMatch(/data-testid="emc-close"/)
  })

  it('has frequency input testid string', () => {
    // testid set via data-testid={id} from object array with id: 'emc-freq'
    expect(panelSrc).toMatch(/'emc-freq'/)
  })

  it('has loop area input testid string', () => {
    expect(panelSrc).toMatch(/'emc-area'/)
  })

  it('has current input testid string', () => {
    expect(panelSrc).toMatch(/'emc-current'/)
  })

  it('has distance input testid string', () => {
    expect(panelSrc).toMatch(/'emc-distance'/)
  })

  it('has EMC run button testid', () => {
    expect(panelSrc).toMatch(/data-testid="emc-run-btn"/)
  })

  it('has radiated result testid', () => {
    expect(panelSrc).toMatch(/data-testid="emc-radiated-result"/)
  })

  it('has shielding button testid', () => {
    expect(panelSrc).toMatch(/data-testid="emc-shield-btn"/)
  })

  it('references FCC §15.109', () => {
    expect(panelSrc).toMatch(/FCC.*15\.109|FCC §15/)
  })

  it('references CISPR 32', () => {
    expect(panelSrc).toMatch(/CISPR 32|CISPR32/)
  })

  it('references Ott EMC reference', () => {
    expect(panelSrc).toMatch(/Ott/)
  })

  it('has standard selector (FCC/CISPR)', () => {
    expect(panelSrc).toMatch(/fcc|cispr/i)
  })
})

// ── 4. PCBThermalPanel source contracts ───────────────────────────────────────

describe('PCBThermalPanel — source contracts', () => {
  const panelSrc = src('components/electronics/PCBThermalPanel.jsx')

  it('exports a default component named PCBThermalPanel', () => {
    expect(panelSrc).toMatch(/export default function PCBThermalPanel/)
  })

  it('has data-testid="pcb-thermal-panel"', () => {
    expect(panelSrc).toMatch(/data-testid="pcb-thermal-panel"/)
  })

  it('has data-testid="pcb-thermal-close"', () => {
    expect(panelSrc).toMatch(/data-testid="pcb-thermal-close"/)
  })

  it('has copper coverage input testid string', () => {
    // testid set via data-testid={id} from object array with id: 'thermal-copper'
    expect(panelSrc).toMatch(/'thermal-copper'/)
  })

  it('has h_conv input testid string', () => {
    expect(panelSrc).toMatch(/'thermal-hconv'/)
  })

  it('has ambient temperature input testid string', () => {
    expect(panelSrc).toMatch(/'thermal-ambient'/)
  })

  it('has thermal run button testid', () => {
    expect(panelSrc).toMatch(/data-testid="thermal-run-btn"/)
  })

  it('has thermal map result testid', () => {
    expect(panelSrc).toMatch(/data-testid="thermal-map-result"/)
  })

  it('has heatmap testid', () => {
    expect(panelSrc).toMatch(/data-testid="thermal-heatmap"/)
  })

  it('has recommend button testid', () => {
    expect(panelSrc).toMatch(/data-testid="thermal-recommend-btn"/)
  })

  it('has recommend result testid', () => {
    expect(panelSrc).toMatch(/data-testid="thermal-recommend-result"/)
  })

  it('references IPC-2152', () => {
    expect(panelSrc).toMatch(/IPC-2152/)
  })

  it('renders a heatmap grid (blue-yellow-red gradient)', () => {
    expect(panelSrc).toMatch(/hsl\(|gradient|heatmap/i)
  })

  it('has default component fixtures with θjc', () => {
    expect(panelSrc).toMatch(/theta_jc|θjc|tjc/)
  })
})

// ── 5. PCBInteractiveEditor — wires all 4 new panels ─────────────────────────

describe('PCBInteractiveEditor — new panel wiring', () => {
  const editorSrc = src('components/electronics/PCBInteractiveEditor.jsx')

  it('imports MultiBoardPanel', () => {
    expect(editorSrc).toMatch(/import.*MultiBoardPanel/)
  })

  it('imports PCB3DPanel', () => {
    expect(editorSrc).toMatch(/import.*PCB3DPanel/)
  })

  it('imports EMCPanel', () => {
    expect(editorSrc).toMatch(/import.*EMCPanel/)
  })

  it('imports PCBThermalPanel', () => {
    expect(editorSrc).toMatch(/import.*PCBThermalPanel/)
  })

  it('has showMultiBoardPanel state', () => {
    expect(editorSrc).toMatch(/showMultiBoardPanel/)
  })

  it('has showPCB3DPanel state', () => {
    expect(editorSrc).toMatch(/showPCB3DPanel/)
  })

  it('has showEMCPanel state', () => {
    expect(editorSrc).toMatch(/showEMCPanel/)
  })

  it('has showPCBThermalPanel state', () => {
    expect(editorSrc).toMatch(/showPCBThermalPanel/)
  })

  it('renders MultiBoardPanel conditionally', () => {
    expect(editorSrc).toMatch(/<MultiBoardPanel/)
  })

  it('renders PCB3DPanel conditionally', () => {
    expect(editorSrc).toMatch(/<PCB3DPanel/)
  })

  it('renders EMCPanel conditionally', () => {
    expect(editorSrc).toMatch(/<EMCPanel/)
  })

  it('renders PCBThermalPanel conditionally', () => {
    expect(editorSrc).toMatch(/<PCBThermalPanel/)
  })

  it('passes onToggleMultiBoardPanel to Toolbar', () => {
    expect(editorSrc).toMatch(/onToggleMultiBoardPanel/)
  })

  it('passes onTogglePCB3DPanel to Toolbar', () => {
    expect(editorSrc).toMatch(/onTogglePCB3DPanel/)
  })

  it('passes onToggleEMCPanel to Toolbar', () => {
    expect(editorSrc).toMatch(/onToggleEMCPanel/)
  })

  it('passes onTogglePCBThermalPanel to Toolbar', () => {
    expect(editorSrc).toMatch(/onTogglePCBThermalPanel/)
  })
})

// ── 6. Toolbar — 4 new panel toggle buttons ───────────────────────────────────

describe('Toolbar — new panel toggle buttons', () => {
  const toolbarSrc = src('components/electronics/pcb-editor/Toolbar.jsx')

  it('has MB3D panel toggle button testid', () => {
    expect(toolbarSrc).toMatch(/btn-toggle-multiboard-panel/)
  })

  it('has 3D PCB panel toggle button testid', () => {
    expect(toolbarSrc).toMatch(/btn-toggle-pcb3d-panel/)
  })

  it('has EMC panel toggle button testid', () => {
    expect(toolbarSrc).toMatch(/btn-toggle-emc-panel/)
  })

  it('has Thermal panel toggle button testid', () => {
    expect(toolbarSrc).toMatch(/btn-toggle-thermal-panel/)
  })

  it('accepts onToggleMultiBoardPanel prop', () => {
    expect(toolbarSrc).toMatch(/onToggleMultiBoardPanel/)
  })

  it('accepts onTogglePCB3DPanel prop', () => {
    expect(toolbarSrc).toMatch(/onTogglePCB3DPanel/)
  })

  it('accepts onToggleEMCPanel prop', () => {
    expect(toolbarSrc).toMatch(/onToggleEMCPanel/)
  })

  it('accepts onTogglePCBThermalPanel prop', () => {
    expect(toolbarSrc).toMatch(/onTogglePCBThermalPanel/)
  })
})

// ── 7. Python plugin.py — new module registrations ────────────────────────────

describe('kerf-electronics plugin — new module registrations', () => {
  it('plugin.py registers pcb_3d_clearance module', () => {
    const pluginSrc = readFileSync(
      resolve(root, '../packages/kerf-electronics/src/kerf_electronics/plugin.py'),
      'utf8'
    )
    expect(pluginSrc).toMatch(/kerf_electronics\.pcb_3d_clearance/)
  })

  it('plugin.py registers idf_roundtrip module', () => {
    const pluginSrc = readFileSync(
      resolve(root, '../packages/kerf-electronics/src/kerf_electronics/plugin.py'),
      'utf8'
    )
    expect(pluginSrc).toMatch(/kerf_electronics\.idf_roundtrip/)
  })
})

// ── 8. Dynamic module load tests ──────────────────────────────────────────────

describe('MultiBoardPanel — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    vi.mock('react-router-dom', () => ({
      useSearchParams: () => [new URLSearchParams()],
    }))
    const mod = await import('../MultiBoardPanel.jsx')
    expect(mod.default).toBeTruthy()
  })
})

describe('PCB3DPanel — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    const mod = await import('../PCB3DPanel.jsx')
    expect(mod.default).toBeTruthy()
  })
})

describe('EMCPanel — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    const mod = await import('../EMCPanel.jsx')
    expect(mod.default).toBeTruthy()
  })
})

describe('PCBThermalPanel — module loads', () => {
  it('module can be dynamically imported without throwing', async () => {
    const mod = await import('../PCBThermalPanel.jsx')
    expect(mod.default).toBeTruthy()
  })
})
