import { describe, it, expect } from 'vitest'
import {
  expandBus,
  validateBus,
  defineBus,
  defineDifferentialPair,
  getDifferentialPair,
  listDifferentialPairs,
  listBuses,
} from './buses.js'

// ── Fixtures ──────────────────────────────────────────────────────────────────

function makeCircuit(overrides = {}) {
  return {
    type: 'pcb_board',
    width: 50,
    height: 50,
    ...overrides,
  }
}

// ── expandBus ─────────────────────────────────────────────────────────────────

describe('expandBus', () => {
  it('passes through a plain net name', () => {
    expect(expandBus('DATA0')).toEqual(['DATA0'])
    expect(expandBus('RX')).toEqual(['RX'])
  })

  it('expands DATA[7..0] descending', () => {
    expect(expandBus('DATA[7..0]')).toEqual([
      'DATA7', 'DATA6', 'DATA5', 'DATA4', 'DATA3', 'DATA2', 'DATA1', 'DATA0',
    ])
  })

  it('expands DATA[0..7] ascending', () => {
    expect(expandBus('DATA[0..7]')).toEqual([
      'DATA0', 'DATA1', 'DATA2', 'DATA3', 'DATA4', 'DATA5', 'DATA6', 'DATA7',
    ])
  })

  it('expands ADDR[3..0] to 4 nets', () => {
    expect(expandBus('ADDR[3..0]')).toEqual(['ADDR3', 'ADDR2', 'ADDR1', 'ADDR0'])
  })

  it('expands a single-bit slice to one net', () => {
    expect(expandBus('BIT[3..3]')).toEqual(['BIT3'])
  })

  it('returns empty array for invalid spec', () => {
    expect(expandBus('')).toEqual([])
    expect(expandBus(null)).toEqual([])
    expect(expandBus(42)).toEqual([])
    expect(expandBus('DATA[]')).toEqual([])
    expect(expandBus('DATA[abc]')).toEqual([])
  })

  it('handles adjacent digits in prefix', () => {
    expect(expandBus('A2[3..0]')).toEqual(['A23', 'A22', 'A21', 'A20'])
  })
})

// ── validateBus ──────────────────────────────────────────────────────────────

describe('validateBus', () => {
  it('returns ok=true for a valid bus', () => {
    const result = validateBus({ name: 'DATA_BUS', member_nets: ['D0', 'D1', 'D2'] })
    expect(result.ok).toBe(true)
    expect(result.errors).toHaveLength(0)
  })

  it('returns ok=true when member uses slice notation', () => {
    const result = validateBus({ name: 'DATA_BUS', member_nets: ['DATA[7..0]'] })
    expect(result.ok).toBe(true)
  })

  it('catches missing name', () => {
    const result = validateBus({ member_nets: ['D0'] })
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('name'))).toBe(true)
  })

  it('catches missing member_nets', () => {
    const result = validateBus({ name: 'BUS' })
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('member_nets'))).toBe(true)
  })

  it('catches empty member_nets array', () => {
    const result = validateBus({ name: 'BUS', member_nets: [] })
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('empty'))).toBe(true)
  })

  it('catches invalid slice notation in member', () => {
    const result = validateBus({ name: 'BUS', member_nets: ['BAD[]]'] })
    expect(result.ok).toBe(false)
    expect(result.errors.some(e => e.includes('invalid slice syntax'))).toBe(true)
  })

  it('catches null input', () => {
    const result = validateBus(null)
    expect(result.ok).toBe(false)
  })
})

// ── defineBus ─────────────────────────────────────────────────────────────────

describe('defineBus', () => {
  it('adds a new bus to the board', () => {
    const circuit = makeCircuit()
    const result = defineBus(circuit, { name: 'DATA_BUS', member_nets: ['D0', 'D1'] })
    expect(result.bus_definitions).toHaveLength(1)
    expect(result.bus_definitions[0].name).toBe('DATA_BUS')
  })

  it('uses bus slice notation to expand members', () => {
    const circuit = makeCircuit()
    const result = defineBus(circuit, { name: 'DATA_BUS', member_nets: ['DATA[7..0]'] })
    expect(result.bus_definitions[0].member_nets).toEqual(['DATA[7..0]'])
  })

  it('updates an existing bus with the same name', () => {
    let circuit = defineBus(makeCircuit(), { name: 'DATA_BUS', member_nets: ['D0'] })
    circuit = defineBus(circuit, { name: 'DATA_BUS', member_nets: ['D0', 'D1', 'D2'] })
    expect(circuit.bus_definitions).toHaveLength(1)
    expect(circuit.bus_definitions[0].member_nets).toHaveLength(3)
  })

  it('does not mutate the original circuit', () => {
    const circuit = makeCircuit()
    defineBus(circuit, { name: 'BUS', member_nets: ['N0'] })
    expect(circuit.bus_definitions).toBeUndefined()
  })

  it('throws on invalid bus def', () => {
    expect(() => defineBus(makeCircuit(), { name: 'BUS' })).toThrow()
  })
})

// ── defineDifferentialPair ─────────────────────────────────────────────────────

describe('defineDifferentialPair', () => {
  it('adds a differential pair to the board', () => {
    const circuit = makeCircuit()
    const result = defineDifferentialPair(circuit, { name: 'USB', net_p: 'USB_P', net_n: 'USB_N' })
    expect(result.differential_pairs).toHaveLength(1)
    expect(result.differential_pairs[0].name).toBe('USB')
    expect(result.differential_pairs[0].net_p_id).toBe('USB_P')
    expect(result.differential_pairs[0].net_n_id).toBe('USB_N')
  })

  it('stores optional impedance and skew fields', () => {
    const circuit = makeCircuit()
    const result = defineDifferentialPair(circuit, {
      name: 'USB',
      net_p: 'USB_P',
      net_n: 'USB_N',
      target_impedance_ohms: 90,
      skew_max_mm: 0.05,
    })
    expect(result.differential_pairs[0].target_impedance_ohms).toBe(90)
    expect(result.differential_pairs[0].skew_max_mm).toBe(0.05)
  })

  it('updates an existing pair with the same name', () => {
    let circuit = defineDifferentialPair(makeCircuit(), { name: 'USB', net_p: 'P', net_n: 'N' })
    circuit = defineDifferentialPair(circuit, { name: 'USB', net_p: 'XP', net_n: 'XN' })
    expect(circuit.differential_pairs).toHaveLength(1)
    expect(circuit.differential_pairs[0].net_p_id).toBe('XP')
  })

  it('does not mutate the original circuit', () => {
    const circuit = makeCircuit()
    defineDifferentialPair(circuit, { name: 'DP', net_p: 'P', net_n: 'N' })
    expect(circuit.differential_pairs).toBeUndefined()
  })

  it('throws when net_p equals net_n', () => {
    expect(() => defineDifferentialPair(makeCircuit(), { name: 'BAD', net_p: 'X', net_n: 'X' })).toThrow()
  })

  it('throws on missing name', () => {
    expect(() => defineDifferentialPair(makeCircuit(), { net_p: 'P', net_n: 'N' })).toThrow()
  })

  it('throws on missing net_p', () => {
    expect(() => defineDifferentialPair(makeCircuit(), { name: 'DP', net_n: 'N' })).toThrow()
  })
})

// ── getDifferentialPair ───────────────────────────────────────────────────────

describe('getDifferentialPair', () => {
  it('returns the pair when net_id matches net_p_id', () => {
    const circuit = defineDifferentialPair(makeCircuit(), { name: 'USB', net_p: 'USB_P', net_n: 'USB_N' })
    const pair = getDifferentialPair(circuit, 'USB_P')
    expect(pair).not.toBeNull()
    expect(pair.name).toBe('USB')
  })

  it('returns the pair when net_id matches net_n_id', () => {
    const circuit = defineDifferentialPair(makeCircuit(), { name: 'USB', net_p: 'USB_P', net_n: 'USB_N' })
    const pair = getDifferentialPair(circuit, 'USB_N')
    expect(pair).not.toBeNull()
    expect(pair.name).toBe('USB')
  })

  it('returns null when net_id is not part of any pair', () => {
    const circuit = defineDifferentialPair(makeCircuit(), { name: 'USB', net_p: 'USB_P', net_n: 'USB_N' })
    expect(getDifferentialPair(circuit, 'GND')).toBeNull()
  })

  it('returns null for empty net_id', () => {
    expect(getDifferentialPair(makeCircuit(), '')).toBeNull()
    expect(getDifferentialPair(makeCircuit(), null)).toBeNull()
  })

  it('returns null when board has no differential_pairs key', () => {
    expect(getDifferentialPair(makeCircuit(), 'USB_P')).toBeNull()
  })
})

// ── listDifferentialPairs ──────────────────────────────────────────────────────

describe('listDifferentialPairs', () => {
  it('returns empty array when no pairs defined', () => {
    expect(listDifferentialPairs(makeCircuit())).toEqual([])
  })

  it('returns all defined pairs', () => {
    let circuit = defineDifferentialPair(makeCircuit(), { name: 'A', net_p: 'AP', net_n: 'AN' })
    circuit = defineDifferentialPair(circuit, { name: 'B', net_p: 'BP', net_n: 'BN' })
    const pairs = listDifferentialPairs(circuit)
    expect(pairs).toHaveLength(2)
    expect(pairs.map(p => p.name).sort()).toEqual(['A', 'B'])
  })

  it('returns a deep copy (mutation does not affect original)', () => {
    const circuit = defineDifferentialPair(makeCircuit(), { name: 'A', net_p: 'AP', net_n: 'AN' })
    const copy = listDifferentialPairs(circuit)
    copy[0].name = 'tampered'
    expect(defineDifferentialPair(makeCircuit(), { name: 'A', net_p: 'AP', net_n: 'AN' }).differential_pairs[0].name).toBe('A')
  })
})

// ── listBuses ───────────────────────────────────────────────────────────────────

describe('listBuses', () => {
  it('returns empty array when no buses defined', () => {
    expect(listBuses(makeCircuit())).toEqual([])
  })

  it('returns all defined buses', () => {
    let circuit = defineBus(makeCircuit(), { name: 'DATA_BUS', member_nets: ['D[7..0]'] })
    circuit = defineBus(circuit, { name: 'ADDR_BUS', member_nets: ['A[15..0]'] })
    const buses = listBuses(circuit)
    expect(buses).toHaveLength(2)
    expect(buses.map(b => b.name).sort()).toEqual(['ADDR_BUS', 'DATA_BUS'])
  })
})
