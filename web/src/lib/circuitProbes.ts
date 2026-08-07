// circuitProbes — synthesise `simulation_probe` records from `// @kerf-probe`
// comments in a `.circuit.tsx` source so circuitToSpice can emit `.print`
// directives. Pure; returns a NEW array (no mutation of input).

import { parseProbes } from './circuitTSX.js'

// Component-id heuristic: tscircuit's `source_component.source_component_id`
// values are typically `simple_<refdes>` (e.g. `simple_resistor_0`,
// `simple_q1`). For an I-probe we treat a PORT token starting with `simple_`
// or containing `component` as a component id; otherwise we route through
// `source_port_id`.
function looksLikeComponentId(token: unknown): boolean {
  if (!token || typeof token !== 'string') return false
  return /^simple[_-]/i.test(token) || /component/i.test(token)
}

/** Synthetic `simulation_probe` record. Not `CircuitElement` — same
 *  "source_* record, not modeled by CircuitElement" situation documented in
 *  `circuitToSpice.ts`'s `SpiceRecord`. */
interface ProbeRecord {
  type: 'simulation_probe'
  _kerf_probe: true
  name: string
  kind: 'V' | 'I'
  source_component_id?: string
  source_port_id?: string
}

/** Append synthetic `simulation_probe` records parsed from `source` to a copy
 *  of `circuitJson`. */
export function injectProbeRecords(circuitJson: unknown, source: string): unknown[] {
  const base = Array.isArray(circuitJson) ? circuitJson : []
  const probes = parseProbes(source)
  if (probes.length === 0) return [...base]
  const records: ProbeRecord[] = probes.map((p) => {
    const rec: ProbeRecord = { type: 'simulation_probe', _kerf_probe: true, name: p.name, kind: p.kind as 'V' | 'I' }
    if (p.kind === 'I' && looksLikeComponentId(p.portId)) {
      rec.source_component_id = p.portId
    } else {
      rec.source_port_id = p.portId
    }
    return rec
  })
  return [...base, ...records]
}
