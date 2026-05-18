// ratsnest.test.jsx — vitest unit tests for the JS MST ratsnest helper.
//
// Tests the pure computeRatsnest / computeNetMST logic exported from
// RatsnestLayer.jsx.  No React render required — all interesting logic is
// in pure functions.

import { describe, it, expect } from 'vitest'
import { computeRatsnest } from './RatsnestLayer.jsx'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePad(padId, x, y, netId = 'NET1') {
  return {
    type: 'pcb_smtpad',
    pcb_smtpad_id: padId,
    x,
    y,
    width: 1.0,
    height: 1.0,
    net_id: netId,
  }
}

function totalLength(edges) {
  return edges.reduce((sum, e) => sum + e.lengthMm, 0)
}

// ---------------------------------------------------------------------------
// Basic cases
// ---------------------------------------------------------------------------

describe('computeRatsnest', () => {
  it('returns empty array for empty circuit', () => {
    expect(computeRatsnest([])).toEqual([])
  })

  it('returns empty array for non-array input', () => {
    expect(computeRatsnest(null)).toEqual([])
    expect(computeRatsnest(undefined)).toEqual([])
  })

  it('returns empty array when no pads have net_id', () => {
    const circuit = [
      { type: 'pcb_smtpad', pcb_smtpad_id: 'P1', x: 0, y: 0 },
      { type: 'pcb_smtpad', pcb_smtpad_id: 'P2', x: 5, y: 0 },
    ]
    expect(computeRatsnest(circuit)).toEqual([])
  })

  it('single-pad net produces no edges', () => {
    const circuit = [makePad('P1', 0, 0, 'LONE')]
    expect(computeRatsnest(circuit)).toEqual([])
  })

  it('two-pad net produces exactly one edge', () => {
    const circuit = [
      makePad('P1', 0, 0, 'VCC'),
      makePad('P2', 3, 0, 'VCC'),
    ]
    const result = computeRatsnest(circuit)
    expect(result).toHaveLength(1)
  })

  it('two-pad edge has correct length (3-4-5 triangle)', () => {
    const circuit = [
      makePad('P1', 0, 0, 'V'),
      makePad('P2', 3, 4, 'V'),
    ]
    const result = computeRatsnest(circuit)
    expect(result).toHaveLength(1)
    expect(result[0].lengthMm).toBeCloseTo(5.0, 9)
  })

  it('MST of unit-square 4-pad net has total length 3', () => {
    const circuit = [
      makePad('TL', 0, 0, 'N'),
      makePad('TR', 1, 0, 'N'),
      makePad('BL', 0, 1, 'N'),
      makePad('BR', 1, 1, 'N'),
    ]
    const result = computeRatsnest(circuit)
    // MST of unit square: 3 edges of length 1 each
    expect(result).toHaveLength(3)
    expect(totalLength(result)).toBeCloseTo(3.0, 9)
  })

  it('MST of collinear pads is shorter than star topology', () => {
    // 5 collinear pads at x=0,1,2,3,4
    const circuit = [0, 1, 2, 3, 4].map((i) => makePad(`P${i}`, i, 0, 'NET'))
    const result = computeRatsnest(circuit)
    const mstLen = totalLength(result)

    // Star from P0: 0+1+2+3+4 = 10; MST = 4 (adjacent pairs sum)
    const starLen = 1 + 2 + 3 + 4
    expect(mstLen).toBeLessThan(starLen)
    expect(mstLen).toBeCloseTo(4.0, 9)
  })

  it('groups pads by net_id independently', () => {
    const circuit = [
      makePad('A1', 0, 0, 'NET_A'),
      makePad('A2', 1, 0, 'NET_A'),
      makePad('B1', 10, 0, 'NET_B'),
      makePad('B2', 12, 0, 'NET_B'),
      makePad('B3', 14, 0, 'NET_B'),
    ]
    const result = computeRatsnest(circuit)
    const netA = result.filter((e) => e.netId === 'NET_A')
    const netB = result.filter((e) => e.netId === 'NET_B')
    expect(netA).toHaveLength(1)   // 2 pads → 1 MST edge
    expect(netB).toHaveLength(2)   // 3 pads → 2 MST edges
  })

  it('each edge has required fields', () => {
    const circuit = [makePad('P1', 0, 0, 'V'), makePad('P2', 1, 0, 'V')]
    const result = computeRatsnest(circuit)
    expect(result).toHaveLength(1)
    const e = result[0]
    expect(e).toHaveProperty('netId')
    expect(e).toHaveProperty('from')
    expect(e).toHaveProperty('to')
    expect(e).toHaveProperty('lengthMm')
    expect(e.from).toHaveProperty('x')
    expect(e.from).toHaveProperty('y')
    expect(e.to).toHaveProperty('x')
    expect(e.to).toHaveProperty('y')
  })

  it('handles pcb_plated_hole pad type', () => {
    const circuit = [
      {
        type: 'pcb_plated_hole',
        pcb_plated_hole_id: 'H1',
        x: 0,
        y: 0,
        net_id: 'GND',
      },
      {
        type: 'pcb_plated_hole',
        pcb_plated_hole_id: 'H2',
        x: 3,
        y: 4,
        net_id: 'GND',
      },
    ]
    const result = computeRatsnest(circuit)
    expect(result).toHaveLength(1)
    expect(result[0].lengthMm).toBeCloseTo(5.0, 9)
  })

  it('ignores non-pad element types', () => {
    const circuit = [
      { type: 'pcb_trace', pcb_trace_id: 'T1', net_id: 'NET', route: [] },
      { type: 'source_component', source_component_id: 'SC1', name: 'R1' },
    ]
    expect(computeRatsnest(circuit)).toEqual([])
  })
})
