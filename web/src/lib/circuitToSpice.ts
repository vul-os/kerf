/**
 * circuitToSpice — pure CircuitJSON → SPICE `.cir` netlist emitter.
 *
 * Pure, hermetic, side-effect-free transform from tscircuit's compiled
 * CircuitJSON array to a SPICE deck string. No engine, no worker, no UI.
 * Engine execution runs server-side on the `pyworker` ngspice subprocess
 * (see `POST /run-spice`); the `.simulation` file kind, SimulationView
 * panel, and `run_simulation` LLM tool consume the netlist this emits.
 *
 * Recognised `source_component.ftype` values (verified against
 * `node_modules/@tscircuit/core` + `node_modules/circuit-json`):
 *   simple_resistor, simple_capacitor, simple_inductor,
 *   simple_voltage_source, simple_diode, simple_transistor, simple_mosfet.
 * (tscircuit collapses BJTs into `simple_transistor`; `simple_bjt_transistor`
 * does NOT exist on disk. We honour both spellings just in case.)
 *
 * Net assignment uses union-find over `source_trace.connected_source_port_ids`
 * — every port reachable through a chain of traces collapses into one SPICE
 * net. Net `0` is GND, taken from any component named `GND` (case-insensitive)
 * or whose ftype is `simple_ground`. Other nets are numbered 1…N in order of
 * first appearance.
 *
 * Probe convention (the schematic probe tool isn't built yet, so this is the
 * forward-compatible shape we'll emit from the future tool):
 *   { type: 'simulation_probe', _kerf_probe: true,
 *     name: 'VOUT', kind: 'V'|'I',
 *     source_port_id?: string,        // for V — net is the port's net
 *     source_component_id?: string }  // for I — refdes is the component
 *
 * Returns `{ netlist, probes, warnings, errors }`. If `errors` is non-empty
 * the netlist still contains the header + `.end` but skips analysis cards;
 * callers should refuse to dispatch it to the engine.
 *
 * --- Typing note: another impedance mismatch (see circuitJsonPatch.ts and
 * src/types/circuit.ts for the others) ---
 * This emitter reads several fields that are NOT part of circuit-json's real
 * schema at all: `waveform` (a nested `{type,offset,amplitude,...}` object —
 * the real `SourceSimpleVoltageSource` only has flat `voltage`/`frequency`/
 * `wave_shape`), `voltage_source_value`, `spice_model`, and the
 * `_kerf_probe`/`simulation_probe` convention documented above as
 * "forward-compatible... for [a probe tool that] isn't built yet." None of
 * that is modeled by circuit-json's `AnySourceElement`, so the public
 * `circuitJson` parameter is typed through the `CircuitJson` alias seam (the
 * real contract callers pass), while this file's *internal* processing works
 * over a local `SpiceRecord` — a Kerf-specific simulation-oriented superset
 * of Circuit JSON's `source_*` records that the real schema doesn't have a
 * type for. One documented cast at the entry point, not scattered `any`.
 */

import type { CircuitJson } from '@/types'

interface SpiceWaveform {
  type?: string
  offset?: number | string
  amplitude?: number | string
  frequency?: number | string
  v1?: number | string
  v2?: number | string
  td?: number | string
  tr?: string
  tf?: string
  pw?: string
  per?: string
}

/** See file header comment for why this isn't `CircuitElement`. */
interface SpiceRecord {
  type?: string
  source_component_id?: string
  source_port_id?: string
  source_trace_id?: string
  name?: string
  ftype?: string
  resistance?: number | string
  capacitance?: number | string
  inductance?: number | string
  voltage?: number | string
  voltage_source_value?: number | string
  waveform?: SpiceWaveform
  spice_model?: string
  pin_number?: number
  connected_source_port_ids?: string[]
  _kerf_probe?: boolean
  probe_name?: string
  kind?: 'V' | 'I'
  [key: string]: unknown
}

export interface SpiceAnalysis {
  type: 'tran' | 'dc' | 'op'
  tstep?: string
  tstop?: string
}

export interface CircuitToSpiceOptions {
  analysis?: SpiceAnalysis
}

export interface SpiceProbe {
  name: string
  kind: 'V' | 'I'
  netOrComp: string | number
}

export interface SpiceResult {
  netlist: string
  probes: SpiceProbe[]
  warnings: string[]
  errors: string[]
}

export function circuitToSpice(circuitJson: CircuitJson, opts: CircuitToSpiceOptions = {}): SpiceResult {
  const warnings: string[] = []
  const errors: string[] = []
  const probes: SpiceProbe[] = []

  // See header comment: this file's internal shape is a superset of real
  // Circuit JSON source_* records, not modeled by `CircuitElement`.
  const records: SpiceRecord[] = Array.isArray(circuitJson) ? (circuitJson as unknown as SpiceRecord[]) : []

  const components = records
    .filter((r) => r && r.type === 'source_component')
    .slice()
    .sort((a, b) => String(a.source_component_id).localeCompare(String(b.source_component_id)))

  const ports = records.filter((r) => r && r.type === 'source_port')
  const traces = records.filter((r) => r && r.type === 'source_trace')

  const portsByComponent = new Map<string | undefined, SpiceRecord[]>()
  for (const p of ports) {
    const list = portsByComponent.get(p.source_component_id) || []
    list.push(p)
    portsByComponent.set(p.source_component_id, list)
  }
  for (const list of portsByComponent.values()) {
    list.sort((a, b) => (a.pin_number ?? 0) - (b.pin_number ?? 0))
  }

  // Union-find over port ids: every trace fuses its connected ports into one
  // equivalence class, which becomes one SPICE net.
  const parent = new Map<string, string>()
  const find = (x: string): string => {
    if (!parent.has(x)) parent.set(x, x)
    let r = x
    while (parent.get(r) !== r) r = parent.get(r) as string
    let cur = x
    while (parent.get(cur) !== r) {
      const nxt = parent.get(cur) as string
      parent.set(cur, r)
      cur = nxt
    }
    return r
  }
  const union = (a: string, b: string): void => {
    const ra = find(a)
    const rb = find(b)
    if (ra !== rb) parent.set(ra, rb)
  }
  for (const p of ports) if (p.source_port_id) find(p.source_port_id)
  for (const t of traces) {
    const ids = Array.isArray(t.connected_source_port_ids) ? t.connected_source_port_ids : []
    for (let i = 1; i < ids.length; i++) union(ids[0], ids[i])
  }

  const groundComponentIds = new Set<string>()
  for (const c of components) {
    const nm = String(c.name || '').toLowerCase()
    if (nm === 'gnd' || nm === 'ground' || c.ftype === 'simple_ground' || c.ftype === 'ground') {
      if (c.source_component_id) groundComponentIds.add(c.source_component_id)
    }
  }
  const groundRoots = new Set<string>()
  for (const p of ports) {
    if (p.source_component_id && groundComponentIds.has(p.source_component_id) && p.source_port_id) {
      groundRoots.add(find(p.source_port_id))
    }
  }

  const netByRoot = new Map<string, number>()
  for (const r of groundRoots) netByRoot.set(r, 0)
  let nextNet = 1
  const netOf = (portId: string | undefined): number | null => {
    if (!portId) return null
    const r = find(portId)
    if (!netByRoot.has(r)) netByRoot.set(r, nextNet++)
    return netByRoot.get(r) as number
  }

  const refdesCounters: Record<string, number> = {}
  const ftypeToPrefix: Record<string, string> = {
    simple_resistor: 'R',
    simple_capacitor: 'C',
    simple_inductor: 'L',
    simple_voltage_source: 'V',
    simple_diode: 'D',
    simple_transistor: 'Q',
    simple_bjt_transistor: 'Q',
    simple_mosfet: 'M',
  }
  const refdesOf = (c: SpiceRecord): string => {
    const prefix = ftypeToPrefix[c.ftype || ''] || 'X'
    if (c.name && /^[A-Za-z][A-Za-z0-9_]*$/.test(c.name)) return c.name
    refdesCounters[prefix] = (refdesCounters[prefix] || 0) + 1
    return `${prefix}${refdesCounters[prefix]}`
  }

  const isFiniteNum = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v)
  const numeric = (v: unknown): number | null => {
    if (isFiniteNum(v)) return v
    if (typeof v === 'string' && v.trim() !== '' && Number.isFinite(Number(v))) return Number(v)
    return null
  }

  const pickPorts = (c: SpiceRecord, n: number): SpiceRecord[] | null => {
    const list = portsByComponent.get(c.source_component_id) || []
    if (list.length < n) return null
    return list.slice(0, n)
  }

  const componentLines: string[] = []
  const modelLines: string[] = []

  for (const c of components) {
    if (c.source_component_id && groundComponentIds.has(c.source_component_id)) continue
    const refdes = refdesOf(c)
    const compPorts = portsByComponent.get(c.source_component_id) || []
    for (const p of compPorts) {
      const idsTouching = traces.some((t) =>
        Array.isArray(t.connected_source_port_ids) && t.connected_source_port_ids.includes(p.source_port_id as string),
      )
      if (!idsTouching) {
        errors.push(`${refdes}: dangling port ${p.source_port_id} (no trace connects it)`)
      }
    }

    switch (c.ftype) {
      case 'simple_resistor': {
        const v = numeric(c.resistance)
        if (v == null) {
          errors.push(`${refdes}: missing or non-numeric resistance`)
          break
        }
        const pp = pickPorts(c, 2)
        if (!pp) { errors.push(`${refdes}: needs 2 ports, found ${compPorts.length}`); break }
        const n1 = netOf(pp[0].source_port_id)
        const n2 = netOf(pp[1].source_port_id)
        componentLines.push(`R${refdes} ${n1} ${n2} ${v}`)
        break
      }
      case 'simple_capacitor': {
        const v = numeric(c.capacitance)
        if (v == null) {
          errors.push(`${refdes}: missing or non-numeric capacitance`)
          break
        }
        const pp = pickPorts(c, 2)
        if (!pp) { errors.push(`${refdes}: needs 2 ports, found ${compPorts.length}`); break }
        const n1 = netOf(pp[0].source_port_id)
        const n2 = netOf(pp[1].source_port_id)
        componentLines.push(`C${refdes} ${n1} ${n2} ${v}`)
        break
      }
      case 'simple_inductor': {
        const v = numeric(c.inductance)
        if (v == null) {
          errors.push(`${refdes}: missing or non-numeric inductance`)
          break
        }
        const pp = pickPorts(c, 2)
        if (!pp) { errors.push(`${refdes}: needs 2 ports, found ${compPorts.length}`); break }
        const n1 = netOf(pp[0].source_port_id)
        const n2 = netOf(pp[1].source_port_id)
        componentLines.push(`L${refdes} ${n1} ${n2} ${v}`)
        break
      }
      case 'simple_voltage_source': {
        const pp = pickPorts(c, 2)
        if (!pp) { errors.push(`${refdes}: needs 2 ports, found ${compPorts.length}`); break }
        const n1 = netOf(pp[0].source_port_id)
        const n2 = netOf(pp[1].source_port_id)
        const dc = numeric(c.voltage ?? c.voltage_source_value)
        const wf = c.waveform
        if (dc == null && (!wf || !wf.type)) {
          errors.push(`${refdes}: voltage source has neither voltage nor waveform`)
          break
        }
        let spec: string
        if (wf && wf.type === 'sine') {
          const off = numeric(wf.offset) ?? 0
          const amp = numeric(wf.amplitude) ?? 1
          const freq = numeric(wf.frequency) ?? 1000
          spec = `SIN(${off} ${amp} ${freq})`
        } else if (wf && wf.type === 'pulse') {
          const v1 = wf.v1 ?? 0
          const v2 = wf.v2 ?? 5
          const td = wf.td ?? 0
          const tr = wf.tr ?? '1n'
          const tf = wf.tf ?? '1n'
          const pw = wf.pw ?? '1u'
          const per = wf.per ?? '2u'
          spec = `PULSE(${v1} ${v2} ${td} ${tr} ${tf} ${pw} ${per})`
        } else {
          spec = `DC ${dc ?? 0}`
        }
        componentLines.push(`V${refdes} ${n1} ${n2} ${spec}`)
        break
      }
      case 'simple_diode': {
        const pp = pickPorts(c, 2)
        if (!pp) { errors.push(`${refdes}: needs 2 ports, found ${compPorts.length}`); break }
        const a = netOf(pp[0].source_port_id)
        const k = netOf(pp[1].source_port_id)
        const model = `DMOD_${refdes}`
        componentLines.push(`D${refdes} ${a} ${k} ${model}`)
        if (c.spice_model) {
          modelLines.push(`.model ${model} D ${c.spice_model}`)
        } else {
          modelLines.push(`.model ${model} D`)
          warnings.push(`${refdes}: no spice_model prop, using generic D`)
        }
        break
      }
      case 'simple_transistor':
      case 'simple_bjt_transistor': {
        const pp = pickPorts(c, 3)
        if (!pp) { errors.push(`${refdes}: needs 3 ports, found ${compPorts.length}`); break }
        const cN = netOf(pp[0].source_port_id)
        const bN = netOf(pp[1].source_port_id)
        const eN = netOf(pp[2].source_port_id)
        const model = `QMOD_${refdes}`
        componentLines.push(`Q${refdes} ${cN} ${bN} ${eN} ${model}`)
        if (c.spice_model) {
          modelLines.push(`.model ${model} NPN ${c.spice_model}`)
        } else {
          modelLines.push(`.model ${model} NPN`)
          warnings.push(`${refdes}: no spice_model prop, using generic NPN`)
        }
        break
      }
      case 'simple_mosfet': {
        const pp = pickPorts(c, 4)
        if (!pp) { errors.push(`${refdes}: needs 4 ports, found ${compPorts.length}`); break }
        const dN = netOf(pp[0].source_port_id)
        const gN = netOf(pp[1].source_port_id)
        const sN = netOf(pp[2].source_port_id)
        const bN = netOf(pp[3].source_port_id)
        const model = `MMOD_${refdes}`
        componentLines.push(`M${refdes} ${dN} ${gN} ${sN} ${bN} ${model}`)
        if (c.spice_model) {
          modelLines.push(`.model ${model} NMOS ${c.spice_model}`)
        } else {
          modelLines.push(`.model ${model} NMOS`)
          warnings.push(`${refdes}: no spice_model prop, using generic NMOS`)
        }
        break
      }
      default:
        warnings.push(`${c.source_component_id}: unsupported ftype "${c.ftype}", skipped`)
    }
  }

  for (const r of records) {
    if (!r || r._kerf_probe !== true) continue
    const name = r.name || r.probe_name || 'PROBE'
    const kind: 'V' | 'I' = r.kind === 'I' ? 'I' : 'V'
    let netOrComp: string | number
    if (kind === 'V') {
      const n = netOf(r.source_port_id)
      if (n == null) {
        warnings.push(`probe ${name}: source_port_id not resolvable`)
        continue
      }
      netOrComp = n
    } else {
      const cid = r.source_component_id
      const c = components.find((cc) => cc.source_component_id === cid)
      if (!c) {
        warnings.push(`probe ${name}: source_component_id not found`)
        continue
      }
      netOrComp = refdesOf(c)
    }
    probes.push({ name, kind, netOrComp })
  }

  const lines: string[] = []
  lines.push('* Generated by Kerf circuitToSpice — DO NOT EDIT')
  lines.push(...componentLines)
  lines.push(...modelLines)

  if (errors.length === 0) {
    const analysis = opts.analysis
    if (analysis && analysis.type === 'tran') {
      lines.push(`.tran ${analysis.tstep ?? '1u'} ${analysis.tstop ?? '1m'}`)
    } else if (analysis && analysis.type === 'dc') {
      lines.push('.op')
    } else if (analysis && analysis.type === 'op') {
      lines.push('.op')
    }
    for (const pr of probes) {
      const arg = pr.kind === 'V' ? `V(${pr.netOrComp})` : `I(${pr.netOrComp})`
      lines.push(`.print TRAN ${arg}`)
    }
  }

  lines.push('.end')
  const netlist = lines.join('\n') + '\n'

  return { netlist, probes, warnings, errors }
}
