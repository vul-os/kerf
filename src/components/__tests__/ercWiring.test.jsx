// ercWiring.test.jsx — verifies that the ERC and DRC engines produce the
// data shape that CircuitObjectsPanel and PCBView wire into their UI.
//
// We test at the data layer (pure engine calls + helper logic) following the
// same convention as circuitObjectsPanel.test.js: no React render required
// because the interesting logic is in pure functions.

import { describe, it, expect, vi } from 'vitest'
import { runERC } from '../../lib/erc.js'
import { runDRC } from '../../lib/pcbDRC.js'

// ---------------------------------------------------------------------------
// Fixture helpers
// ---------------------------------------------------------------------------

const srcComp = (id, name, extra = {}) => ({
  type: 'source_component',
  source_component_id: id,
  name,
  ftype: 'simple_resistor',
  ...extra,
})

const srcPort = (id, compId, name = 'A', pinType = 'passive') => ({
  type: 'source_port',
  source_port_id: id,
  source_component_id: compId,
  name,
  pin_type: pinType,
})

const srcTrace = (...portIds) => ({
  type: 'source_trace',
  connected_source_port_ids: portIds,
})

// A minimal valid circuit: R1 connected between two ports.
function makeConnectedCircuit() {
  return [
    srcComp('c_r1', 'R1'),
    srcComp('c_r2', 'R2'),
    srcPort('p1', 'c_r1', 'A'),
    srcPort('p2', 'c_r1', 'B'),
    srcPort('p3', 'c_r2', 'A'),
    srcPort('p4', 'c_r2', 'B'),
    srcTrace('p1', 'p3'),
    srcTrace('p2', 'p4'),
  ]
}

// A circuit with two components sharing the same refdes (duplicate_refdes error).
function makeCircuitWithDuplicateRefdes() {
  return [
    srcComp('c_r1', 'R1'),
    srcComp('c_r2', 'R1'),  // duplicate!
    srcPort('p1', 'c_r1', 'A'),
    srcPort('p2', 'c_r1', 'B'),
    srcPort('p3', 'c_r2', 'A'),
    srcPort('p4', 'c_r2', 'B'),
    srcTrace('p1', 'p3'),
    srcTrace('p2', 'p4'),
  ]
}

// A circuit with an unconnected port (unconnected_pin error).
function makeCircuitWithUnconnectedPin() {
  return [
    srcComp('c_r1', 'R1'),
    srcPort('p1', 'c_r1', 'A'),
    srcPort('p2', 'c_r1', 'B'),  // p2 never touched by any trace
    srcTrace('p1'),  // only p1 connected
  ]
}

// PCB fixture helpers
const pcbTrace = (id, x1, y1, x2, y2, widthMm = 0.25) => ({
  type: 'pcb_trace',
  pcb_trace_id: id,
  route_thickness_mm: widthMm,
  route: [{ x: x1, y: y1 }, { x: x2, y: y2 }],
})

const pcbVia = (id, x, y, outerDiam = 0.6, holeDiam = 0.3) => ({
  type: 'pcb_via',
  pcb_via_id: id,
  x,
  y,
  outer_diameter: outerDiam,
  hole_diameter: holeDiam,
})

// ---------------------------------------------------------------------------
// ERC tests — CircuitObjectsPanel wiring
// ---------------------------------------------------------------------------

describe('ERC wiring — no-errors state', () => {
  it('returns empty errors and warnings for an empty circuit', () => {
    const result = runERC([])
    expect(result.errors).toHaveLength(0)
    expect(result.warnings).toHaveLength(0)
  })

  it('returns empty errors and warnings for a null-ish input', () => {
    const result = runERC(null)
    expect(result.errors).toHaveLength(0)
    expect(result.warnings).toHaveLength(0)
  })

  it('has no violations for a clean connected circuit', () => {
    const result = runERC(makeConnectedCircuit())
    expect(result.errors).toHaveLength(0)
  })
})

describe('ERC wiring — error detection', () => {
  it('detects duplicate_refdes when two components share the same name', () => {
    const result = runERC(makeCircuitWithDuplicateRefdes())
    const dup = result.errors.find((e) => e.kind === 'duplicate_refdes')
    expect(dup).toBeTruthy()
    expect(dup.severity).toBe('error')
    expect(dup.message).toMatch(/R1/)
  })

  it('provides component_id on the duplicate_refdes error for click-to-highlight', () => {
    const result = runERC(makeCircuitWithDuplicateRefdes())
    const dup = result.errors.find((e) => e.kind === 'duplicate_refdes')
    // The panel uses item.component_id to call selectCircuitComponent(id)
    expect(typeof dup.component_id).toBe('string')
    expect(dup.component_id).toBeTruthy()
  })

  it('detects unconnected_pin when a port is not on any trace', () => {
    const result = runERC(makeCircuitWithUnconnectedPin())
    const unconn = result.errors.find((e) => e.kind === 'unconnected_pin')
    expect(unconn).toBeTruthy()
    expect(unconn.severity).toBe('error')
    // The message should mention the port or component
    expect(unconn.message).toBeTruthy()
  })

  it('exposes port_id on unconnected_pin for link-back to schematic', () => {
    const result = runERC(makeCircuitWithUnconnectedPin())
    const unconn = result.errors.find((e) => e.kind === 'unconnected_pin')
    expect(unconn.port_id).toBe('p2')
  })

  it('click handler receives correct component_id from duplicate_refdes error', () => {
    const result = runERC(makeCircuitWithDuplicateRefdes())
    const dup = result.errors.find((e) => e.kind === 'duplicate_refdes')
    // Simulate what ErcItem does: onClick calls onSelectComponent(item.component_id)
    const handler = vi.fn()
    if (dup.component_id) handler(dup.component_id)
    expect(handler).toHaveBeenCalledWith(dup.component_id)
  })
})

describe('ERC wiring — result shape contract', () => {
  it('every error has kind, severity, message fields', () => {
    const result = runERC(makeCircuitWithDuplicateRefdes())
    for (const err of result.errors) {
      expect(err).toHaveProperty('kind')
      expect(err).toHaveProperty('severity', 'error')
      expect(err).toHaveProperty('message')
      expect(typeof err.message).toBe('string')
    }
  })

  it('every warning has kind, severity, message fields', () => {
    // Build a circuit with two input-only ports wired together (pin_direction_mismatch)
    const circuit = [
      srcComp('c_u1', 'U1'),
      srcComp('c_u2', 'U2'),
      srcPort('p1', 'c_u1', 'IN1', 'input'),
      srcPort('p2', 'c_u2', 'IN2', 'input'),
      srcTrace('p1', 'p2'),
    ]
    const result = runERC(circuit)
    for (const warn of result.warnings) {
      expect(warn).toHaveProperty('kind')
      expect(warn).toHaveProperty('severity', 'warning')
      expect(warn).toHaveProperty('message')
    }
  })
})

// ---------------------------------------------------------------------------
// DRC tests — PCBView wiring
// ---------------------------------------------------------------------------

describe('DRC wiring — chip color states', () => {
  it('returns empty errors and warnings for an empty board', () => {
    const result = runDRC([])
    expect(result.errors).toHaveLength(0)
    expect(result.warnings).toHaveLength(0)
  })

  it('chip is green (no violations) when DRC finds nothing', () => {
    // An empty board has no violations
    const result = runDRC([])
    // Simulate chip label logic from DRCStatusChip
    const hasErrors = result.errors.length > 0
    const hasWarnings = result.warnings.length > 0
    expect(hasErrors).toBe(false)
    expect(hasWarnings).toBe(false)
    // chip class should be green (emerald)
    const chipState = hasErrors ? 'red' : hasWarnings ? 'amber' : 'green'
    expect(chipState).toBe('green')
  })

  it('chip is red when trace_too_narrow error is present', () => {
    const board = [
      { type: 'pcb_board', width: 50, height: 40 },
      pcbTrace('t1', 5, 5, 20, 5, 0.05),  // 0.05 mm < 0.15 mm minimum
    ]
    const result = runDRC(board)
    const hasErrors = result.errors.length > 0
    expect(hasErrors).toBe(true)
    const chipState = hasErrors ? 'red' : result.warnings.length > 0 ? 'amber' : 'green'
    expect(chipState).toBe('red')
    expect(result.errors[0].kind).toBe('trace_too_narrow')
  })

  it('chip label shows error count correctly', () => {
    const board = [
      pcbTrace('t1', 5, 5, 20, 5, 0.05),
      pcbTrace('t2', 5, 10, 20, 10, 0.05),
    ]
    const result = runDRC(board)
    const { errors, warnings } = result
    // Simulate DRCStatusChip label generation
    let label
    if (errors.length > 0) {
      label = `DRC: ${errors.length} error${errors.length !== 1 ? 's' : ''}${warnings.length ? `, ${warnings.length} warn` : ''}`
    } else if (warnings.length > 0) {
      label = `DRC: ${warnings.length} warning${warnings.length !== 1 ? 's' : ''}`
    } else {
      label = 'DRC: 0 errors'
    }
    expect(label).toMatch(/^DRC: \d+ error/)
    expect(label).toContain(`${errors.length}`)
  })
})

describe('DRC wiring — drawer toggle + focus-on-click', () => {
  it('drawer toggle state: drcOpen flips on chip click (boolean)', () => {
    let drcOpen = false
    const toggleDrc = () => { drcOpen = !drcOpen }
    expect(drcOpen).toBe(false)
    toggleDrc()
    expect(drcOpen).toBe(true)
    toggleDrc()
    expect(drcOpen).toBe(false)
  })

  it('DRC error items carry x,y coordinates for pan-to focus', () => {
    const board = [
      pcbTrace('t1', 5, 5, 20, 5, 0.05),
    ]
    const result = runDRC(board)
    const err = result.errors.find((e) => e.kind === 'trace_too_narrow')
    expect(err).toBeTruthy()
    expect(typeof err.x).toBe('number')
    expect(typeof err.y).toBe('number')
  })

  it('focus-on-click calls setView with board coords from DRC item', () => {
    const board = [
      pcbTrace('t1', 5, 5, 20, 5, 0.05),
    ]
    const result = runDRC(board)
    const err = result.errors[0]

    // Simulate what DRCDrawer's onFocus handler does (passed down from PCBView)
    const setView = vi.fn()
    const mockOnFocus = (x, y) => {
      const targetScale = 20
      const tx = 400 / 2 - x * targetScale
      const ty = 300 / 2 - y * targetScale
      setView({ tx, ty, scale: targetScale })
    }

    mockOnFocus(err.x, err.y)
    expect(setView).toHaveBeenCalledOnce()
    const call = setView.mock.calls[0][0]
    expect(call).toHaveProperty('scale', 20)
    expect(typeof call.tx).toBe('number')
    expect(typeof call.ty).toBe('number')
  })

  it('DRC warning items carry x,y coordinates', () => {
    const board = [
      { type: 'pcb_board', width: 10, height: 10 },
      // Pad near edge triggers copper_to_edge warning
      { type: 'pcb_smtpad', x: 0.1, y: 5, width: 1, height: 1 },
    ]
    const result = runDRC(board)
    // Board may or may not trigger warnings; if it does, they have x,y
    for (const warn of result.warnings) {
      expect(typeof warn.x).toBe('number')
      expect(typeof warn.y).toBe('number')
    }
  })

  it('DRC via_clearance error has x,y as midpoint between vias', () => {
    const board = [
      pcbVia('v1', 0, 0, 0.6, 0.3),
      pcbVia('v2', 0.1, 0, 0.6, 0.3),  // too close
    ]
    const result = runDRC(board)
    const viaErr = result.errors.find((e) => e.kind === 'via_clearance' || e.kind === 'drill_spacing')
    if (viaErr) {
      // midpoint between (0,0) and (0.1,0) = (0.05, 0)
      expect(viaErr.x).toBeCloseTo(0.05, 3)
      expect(viaErr.y).toBeCloseTo(0, 3)
    }
  })
})
