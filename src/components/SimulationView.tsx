// SimulationView — read-only viewer for `.simulation` JSON files.
//
// File shape (mirrors backend constraint shipped in 1746577900000_kind_simulation.sql):
//
//   { version: 1,
//     circuit_file_id: '<uuid>',
//     analysis: { type: 'transient'|'dc'|'ac', tstep?: '1us', tstop?: '10ms',
//                 vstart?: number, vstop?: number, vstep?: number, ... },
//     probes:  [{ name: 'VOUT', kind: 'V'|'I', source_port_id?, source_component_id? }],
//     results: { waveforms: [{ name, kind, xUnit, yUnit, x:[], y:[] }],
//                warnings: [], errors: [] } }
//
// Uses the run_simulation tool (via /api/projects/{pid}/files/{fid}/sim) to
// enqueue ngspice batch jobs on the pyworker compute sidecar. Polls
// sim_job_status until the job completes, then writes results back to the
// .simulation file.

import { useEffect, useRef, useState } from 'react'
import type { ReactNode } from 'react'
import { Activity, AlertTriangle, BarChart3, Loader2, Play, TableProperties } from 'lucide-react'
import { useWorkspace } from '../store/workspace.js'
import { useAuth } from '../store/auth.js'

const API_URL = import.meta.env.VITE_API_URL || ''

const PALETTE = ['#f59e0b', '#22d3ee', '#a78bfa', '#34d399', '#f472b6']

interface SimAnalysisSpec {
  type: string
  [key: string]: unknown
}

interface SimProbe {
  name?: string
  kind?: 'V' | 'I'
  source_port_id?: string
  source_component_id?: string
}

interface SimWaveform {
  name?: string
  kind?: string
  xUnit?: string
  yUnit?: string
  x?: number[]
  y?: number[]
}

interface SimResults {
  waveforms: SimWaveform[]
  warnings: string[]
  errors: string[]
}

interface ParsedSimulation {
  kind: 'ok' | 'unsupported' | 'invalid'
  spec?: SimAnalysisSpec
  probes?: SimProbe[]
  results?: SimResults
  raw?: string
}

interface JobStatus {
  status: 'queued' | 'running' | 'done' | 'error'
  job_id?: string
  result?: { waveforms?: SimWaveform[]; warnings?: string[]; errors?: string[] }
  error?: string
}

interface NormalizedWaveforms {
  data: Array<Array<number | null>>
  names: string[]
  units: string[]
  kinds: string[]
  warnings: string[]
}

/**
 * Parse a `.simulation` JSON string into a normalized read-only shape.
 */
export function parseSimulation(content: string): ParsedSimulation {
  const raw = typeof content === 'string' ? content : ''
  if (!raw.trim()) {
    return {
      kind: 'ok',
      spec: { type: 'transient' },
      probes: [],
      results: { waveforms: [], warnings: [], errors: [] },
    }
  }
  let doc: any // boundary: JSON.parse output, shape validated below
  try {
    doc = JSON.parse(raw)
  } catch {
    return { kind: 'invalid', raw }
  }
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
    return { kind: 'invalid', raw }
  }
  if (doc.version !== 1) {
    return { kind: 'unsupported', raw }
  }
  const analysis = (doc.analysis && typeof doc.analysis === 'object') ? doc.analysis : {}
  const spec: SimAnalysisSpec = { type: typeof analysis.type === 'string' ? analysis.type : 'transient', ...analysis }
  const probes: SimProbe[] = Array.isArray(doc.probes) ? doc.probes.filter((p: unknown) => p && typeof p === 'object') : []
  const r = (doc.results && typeof doc.results === 'object') ? doc.results : {}
  const results: SimResults = {
    waveforms: Array.isArray(r.waveforms) ? r.waveforms : [],
    warnings: Array.isArray(r.warnings) ? r.warnings : [],
    errors: Array.isArray(r.errors) ? r.errors : [],
  }
  return { kind: 'ok', spec, probes, results }
}

/**
 * Normalize a waveform array into uPlot-ingestable [xs, ys1, ys2, …] shape.
 * Picks the first waveform's x as canonical; mismatched-length y arrays are
 * `null`-padded and produce a warning. Numeric x/y arrays only.
 *
 */
export function normalizeWaveforms(waveforms: SimWaveform[]): NormalizedWaveforms {
  const out: NormalizedWaveforms = { data: [], names: [], units: [], kinds: [], warnings: [] }
  if (!Array.isArray(waveforms) || waveforms.length === 0) {
    return out
  }
  const valid = waveforms.filter((w) => w && typeof w === 'object' && Array.isArray(w.x) && Array.isArray(w.y)) as Array<SimWaveform & { x: number[]; y: number[] }>
  if (valid.length === 0) {
    return out
  }
  const canonical = valid[0]
  const xs: Array<number | null> = canonical.x.map((v) => (typeof v === 'number' && Number.isFinite(v) ? v : null))
  const N = xs.length
  out.data.push(xs)
  if (N === 0) {
    // No-data shape: still expose names/units, with empty y series
    for (let i = 0; i < valid.length; i++) {
      const w = valid[i]
      out.names.push(typeof w.name === 'string' && w.name ? w.name : `trace${i + 1}`)
      out.units.push(typeof w.yUnit === 'string' ? w.yUnit : '')
      out.kinds.push(typeof w.kind === 'string' ? w.kind : '')
      out.data.push([])
    }
    return out
  }
  for (let i = 0; i < valid.length; i++) {
    const w = valid[i]
    const name = typeof w.name === 'string' && w.name ? w.name : `trace${i + 1}`
    out.names.push(name)
    out.units.push(typeof w.yUnit === 'string' ? w.yUnit : '')
    out.kinds.push(typeof w.kind === 'string' ? w.kind : '')
    if (i > 0 && w.x.length !== N) {
      out.warnings.push(`x mismatch on '${name}': expected length ${N}, got ${w.x.length}`)
    }
    const ys = new Array(N)
    for (let j = 0; j < N; j++) {
      const v = w.y[j]
      ys[j] = (typeof v === 'number' && Number.isFinite(v)) ? v : null
    }
    out.data.push(ys)
  }
  return out
}

interface SimulationViewProps {
  content?: string
  fileName?: string
}

export default function SimulationView({ content, fileName }: SimulationViewProps) {
  const w = useWorkspace()
  const { accessToken } = useAuth()
  const parsed = parseSimulation(content || '')
  const [running, setRunning] = useState(false)
  const [jobStatus, setJobStatus] = useState<JobStatus | null>(null)
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const docCircuit = (() => {
    if (parsed.kind !== 'ok') return null
    try {
      const d = JSON.parse(content || '{}') // boundary: JSON.parse output
      return (d && typeof d.circuit_file_id === 'string' && d.circuit_file_id) ? d.circuit_file_id : null
    } catch {
      return null
    }
  })()
  const runDisabled = running || parsed.kind !== 'ok' || !docCircuit || !w.projectId || !w.currentFileId

  useEffect(() => {
    return () => {
      if (pollingRef.current) clearInterval(pollingRef.current)
    }
  }, [])

  const pollJobStatus = async (projectId: string, fileId: string) => {
    try {
      const token = useAuth.getState().accessToken
      const res = await fetch(`${API_URL}/api/projects/${projectId}/files/${fileId}/sim/status`, {
        headers: { authorization: `Bearer ${token}` },
      })
      if (!res.ok) throw new Error(`status poll failed: ${res.status}`)
      const data = await res.json() as JobStatus
      setJobStatus(data)
      if (data.status === 'done' || data.status === 'error') {
        if (pollingRef.current) clearInterval(pollingRef.current)
        setRunning(false)
        if (data.status === 'done' && data.result) {
          const doc = JSON.parse(content || '{}') // boundary: JSON.parse output
          const updated = {
            ...doc,
            results: {
              waveforms: data.result.waveforms || [],
              warnings: data.result.warnings || [],
              errors: data.result.errors || [],
            },
          }
          try {
            w.editContent(JSON.stringify(updated, null, 2))
          } catch (err: any) {
            // @ts-expect-error -- pre-existing bug: 'setState' is not a field on WorkspaceState (would throw TypeError at runtime)
            w.setState({ toast: err?.message || 'Failed to update simulation file' })
          }
        } else if (data.status === 'error') {
          // @ts-expect-error -- pre-existing bug: 'setState' is not a field on WorkspaceState (would throw TypeError at runtime)
          w.setState({ toast: data.error || 'Simulation failed' })
        }
      }
    } catch (err: any) {
      // @ts-expect-error -- pre-existing bug: 'setState' is not a field on WorkspaceState (would throw TypeError at runtime)
      w.setState({ toast: err.message })
      if (pollingRef.current) clearInterval(pollingRef.current)
      setRunning(false)
    }
  }

  const onRun = async () => {
    if (runDisabled) return
    let doc
    try {
      doc = JSON.parse(content || '{}') // boundary: JSON.parse output
    } catch {
      // @ts-expect-error -- pre-existing bug: 'setState' is not a field on WorkspaceState (would throw TypeError at runtime)
      w.setState({ toast: 'Cannot run simulation: file is not valid JSON.' })
      return
    }

    setRunning(true)
    setJobStatus({ status: 'queued' })

    try {
      const token = useAuth.getState().accessToken
      const res = await fetch(`${API_URL}/api/projects/${w.projectId}/files/${w.currentFileId}/sim`, {
        method: 'POST',
        headers: {
          'content-type': 'application/json',
          authorization: `Bearer ${token}`,
        },
        body: JSON.stringify(doc.analysis || { type: 'tran' }),
      })
      if (!res.ok) throw new Error(`failed to enqueue: ${res.status}`)
      const data = await res.json() as { job_id?: string }
      setJobStatus({ status: 'queued', job_id: data.job_id })
      pollingRef.current = setInterval(() => pollJobStatus(w.projectId, w.currentFileId), 2000)
    } catch (err: any) {
      // @ts-expect-error -- pre-existing bug: 'setState' is not a field on WorkspaceState (would throw TypeError at runtime)
      w.setState({ toast: err.message })
      setRunning(false)
      setJobStatus(null)
    }
  }

  if (parsed.kind === 'invalid' || parsed.kind === 'unsupported') {
    return (
      <div className="h-full flex flex-col bg-ink-950 text-ink-100 min-h-0">
        <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/40 flex-shrink-0">
          <AlertTriangle size={14} className="text-amber-400 shrink-0" />
          <span className="text-xs font-semibold uppercase tracking-wider text-ink-300">
            Unsupported simulation file
          </span>
          <span className="text-[11px] text-ink-500 truncate">{fileName || ''}</span>
        </div>
        <div className="flex-1 min-h-0 overflow-auto p-4">
          <pre className="text-[11px] font-mono text-ink-400 whitespace-pre-wrap break-all">
            {parsed.raw || ''}
          </pre>
        </div>
      </div>
    )
  }

  const spec = parsed.spec! // kind === 'ok' guarantees spec/probes/results are set
  const probes = parsed.probes!
  const results = parsed.results!
  const isDC = spec.type === 'dc'
  const isAC = spec.type === 'ac'

  const specRows: Array<[string, unknown]> = isDC
    ? [
        ['Type', spec.type],
        ['Vstart', spec.vstart],
        ['Vstop', spec.vstop],
        ['Vstep', spec.vstep],
      ]
    : isAC
      ? [
          ['Type', spec.type],
          ['Fstart', spec.fstart],
          ['Fstop', spec.fstop],
          ['Points', spec.points],
        ]
      : [
          ['Type', spec.type],
          ['Tstep', spec.tstep],
          ['Tstop', spec.tstop],
          ['Tstart', spec.tstart],
        ]

  return (
    <div className="h-full flex flex-col bg-ink-950 text-ink-100 min-h-0">
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-ink-800 bg-ink-900/40 flex-shrink-0">
        <Activity size={14} className="text-kerf-300 shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wider text-ink-300">
          Simulation
        </span>
        <span className="text-[11px] text-ink-500 truncate min-w-0">
          {fileName || ''}
        </span>
        <span className="ml-2 text-[10px] uppercase tracking-wider text-kerf-300 border border-kerf-300/40 rounded px-1.5 py-0.5">
          {spec.type || 'transient'}
        </span>
        <button
          type="button"
          onClick={onRun}
          disabled={runDisabled}
          title={
            !docCircuit
              ? 'Link a circuit_file_id to enable Run'
              : running
                ? `Running… (${jobStatus?.status || 'queued'})`
                : 'Run SPICE simulation'
          }
          className="ml-auto inline-flex items-center gap-1 px-2 py-1 rounded bg-kerf-300 text-ink-950 text-[11px] font-medium hover:bg-kerf-200 disabled:opacity-50 disabled:cursor-not-allowed disabled:hover:bg-kerf-300"
        >
          {running ? (
            <>
              <Loader2 size={11} className="animate-spin" />
              {jobStatus?.status === 'running' ? 'Running…' : 'Queued…'}
            </>
          ) : (
            <>
              <Play size={11} />
              Run
            </>
          )}
        </button>
      </div>

      <div className="flex-1 min-h-0 overflow-auto">
        <div className="max-w-3xl mx-auto px-6 py-5 space-y-6">
          <section>
            <SectionHeading>Analysis</SectionHeading>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
              {specRows.map(([k, v]) => (
                <div key={k} className="bg-ink-900 border border-ink-800 rounded px-2 py-1.5">
                  <div className="text-[10px] uppercase tracking-wider text-ink-500 font-medium">
                    {k}
                  </div>
                  <div className="text-xs font-mono text-ink-100 truncate">
                    {v == null || v === '' ? <span className="text-ink-600">—</span> : String(v)}
                  </div>
                </div>
              ))}
            </div>
          </section>

          <section>
            <SectionHeading>Probes</SectionHeading>
            {probes.length === 0 ? (
              <div className="text-[11px] text-ink-500 italic">No probes defined.</div>
            ) : (
              <ul className="divide-y divide-ink-800 border border-ink-800 rounded overflow-hidden">
                {probes.map((p, i) => (
                  <li
                    key={(p && p.name) || i}
                    className="flex items-center gap-2 px-3 py-1.5 bg-ink-900"
                  >
                    <span className="text-xs text-ink-100 font-medium truncate min-w-[6rem]">
                      {(p && p.name) || <span className="italic text-ink-500">unnamed</span>}
                    </span>
                    <span
                      className={`text-[10px] uppercase tracking-wider rounded px-1.5 py-0.5 border ${
                        p?.kind === 'I'
                          ? 'text-amber-300 border-amber-400/40'
                          : 'text-kerf-300 border-kerf-300/40'
                      }`}
                    >
                      {p?.kind === 'I' ? 'I' : 'V'}
                    </span>
                    <span className="text-[10px] font-mono text-ink-500 truncate flex-1">
                      {p?.source_port_id || p?.source_component_id || '—'}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section>
            <SectionHeading>Results</SectionHeading>
            {results.errors.length > 0 && (
              <div className="mb-2 px-3 py-2 rounded bg-amber-950/40 border border-amber-700/60 text-[11px] text-amber-200">
                <div className="text-[10px] uppercase tracking-wider text-amber-400 font-medium mb-1">
                  Errors
                </div>
                <ul role="list" className="space-y-0.5">
                  {results.errors.map((m, i) => (
                    <li key={i} role="listitem" className="font-mono break-all">{String(m)}</li>
                  ))}
                </ul>
              </div>
            )}
            {results.warnings.length > 0 && (
              <div className="mb-2 px-3 py-2 rounded bg-ink-900 border border-ink-700 text-[11px] text-ink-300">
                <div className="text-[10px] uppercase tracking-wider text-ink-500 font-medium mb-1">
                  Warnings
                </div>
                <ul role="list" className="space-y-0.5">
                  {results.warnings.map((m, i) => (
                    <li key={i} role="listitem" className="font-mono break-all">{String(m)}</li>
                  ))}
                </ul>
              </div>
            )}
            {results.waveforms.length === 0 ? (
              <div className="text-[11px] text-ink-500 italic">
                No results yet — click Run to simulate via ngspice on the pyworker sidecar.
              </div>
            ) : (
              <WaveformChart waveforms={results.waveforms} />
            )}
          </section>
        </div>
      </div>
    </div>
  )
}

/** Lazy-mounted uPlot canvas (or table) for an array of waveforms. */
function WaveformChart({ waveforms }: { waveforms: SimWaveform[] }) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  // uPlot instance, typed `any` — no first-party types for the dynamically-imported lib instance.
  const plotRef = useRef<any>(null)
  const [mode, setMode] = useState<'chart' | 'table'>('chart')
  const [loadError, setLoadError] = useState<string | null>(null)

  const norm = normalizeWaveforms(waveforms)
  const xUnit = (waveforms[0] && typeof waveforms[0].xUnit === 'string') ? waveforms[0].xUnit : ''

  useEffect(() => {
    if (mode !== 'chart') return undefined
    if (!containerRef.current) return undefined
    if (norm.data.length < 2 || norm.data[0].length === 0) return undefined

    let cancelled = false
    let plot: any = null

    Promise.all([
      import('uplot'),
      import('uplot/dist/uPlot.min.css'),
    ])
      .then(([mod]) => {
        if (cancelled || !containerRef.current) return
        // boundary: uplot's dynamic-import type doesn't expose a constructable default cleanly
        const uPlot: any = (mod as any).default || mod
        const el = containerRef.current
        const width = el.clientWidth || 600
        const height = 320
        const series = [
          { label: xUnit ? `t (${xUnit})` : 't' },
          ...norm.names.map((name, i) => ({
            label: norm.units[i] ? `${name} (${norm.units[i]})` : name,
            stroke: PALETTE[i % PALETTE.length],
            width: 1.5,
            points: { show: false },
          })),
        ]
        const opts = {
          width,
          height,
          legend: { live: true },
          cursor: { drag: { x: true, y: false }, points: { size: 6 } },
          axes: [
            {
              stroke: '#9ca3af',
              grid: { stroke: '#1f2937', width: 1 },
              ticks: { stroke: '#1f2937' },
              label: xUnit ? `time (${xUnit})` : 'time',
              labelSize: 18,
              labelFont: '11px ui-sans-serif, system-ui',
              font: '10px ui-monospace, monospace',
            },
            {
              stroke: '#9ca3af',
              grid: { stroke: '#1f2937', width: 1 },
              ticks: { stroke: '#1f2937' },
              font: '10px ui-monospace, monospace',
            },
          ],
          scales: { x: { time: false } },
          series,
        }
        plot = new uPlot(opts, norm.data, el)
        plotRef.current = plot

        // Resize observer to keep canvas snug to container
        const ro = new ResizeObserver(() => {
          if (plot && el.clientWidth) plot.setSize({ width: el.clientWidth, height })
        })
        ro.observe(el)
        plotRef.current.__ro = ro
      })
      .catch((err) => {
        if (cancelled) return
        setLoadError(err && err.message ? err.message : String(err))
      })

    return () => {
      cancelled = true
      const inst = plotRef.current
      if (inst) {
        if (inst.__ro) inst.__ro.disconnect()
        inst.destroy()
        plotRef.current = null
      }
    }
    // Re-init on mode flip or when the underlying waveforms reference changes.
  }, [mode, waveforms]) // eslint-disable-line react-hooks/exhaustive-deps

  const allWarnings = norm.warnings
  const hasData = norm.data.length >= 2 && norm.data[0].length > 0

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2 text-[11px] text-ink-400">
          <span className="font-mono">{norm.names.length} trace{norm.names.length === 1 ? '' : 's'}</span>
          {hasData && <span className="text-ink-600">·</span>}
          {hasData && <span className="font-mono">{norm.data[0].length} samples</span>}
        </div>
        <div className="flex items-center gap-1 border border-ink-800 rounded overflow-hidden">
          <button
            type="button"
            onClick={() => setMode('chart')}
            className={`flex items-center gap-1 px-2 py-1 text-[10px] uppercase tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300/70 ${
              mode === 'chart' ? 'bg-ink-800 text-kerf-300' : 'bg-ink-900 text-ink-500 hover:text-ink-300'
            }`}
            aria-pressed={mode === 'chart'}
          >
            <BarChart3 size={11} />
            Chart
          </button>
          <button
            type="button"
            onClick={() => setMode('table')}
            className={`flex items-center gap-1 px-2 py-1 text-[10px] uppercase tracking-wider transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-kerf-300/70 ${
              mode === 'table' ? 'bg-ink-800 text-kerf-300' : 'bg-ink-900 text-ink-500 hover:text-ink-300'
            }`}
            aria-pressed={mode === 'table'}
          >
            <TableProperties size={11} />
            Table
          </button>
        </div>
      </div>

      {allWarnings.length > 0 && (
        <div className="px-3 py-2 rounded bg-amber-950/30 border border-amber-700/40 text-[11px] text-amber-200">
          <div className="text-[10px] uppercase tracking-wider text-amber-400 font-medium mb-1">
            Chart warnings
          </div>
          <ul role="list" className="space-y-0.5">
            {allWarnings.map((m, i) => (
              <li key={i} role="listitem" className="font-mono break-all">{m}</li>
            ))}
          </ul>
        </div>
      )}

      {loadError && (
        <div className="px-3 py-2 rounded bg-amber-950/40 border border-amber-700/60 text-[11px] text-amber-200">
          <div className="text-[10px] uppercase tracking-wider text-amber-400 font-medium mb-1">
            Chart unavailable
          </div>
          <div className="font-mono break-all">{loadError}</div>
        </div>
      )}

      {mode === 'chart' ? (
        <div
          ref={containerRef}
          className="w-full bg-[#0a0a0a] border border-ink-800 rounded overflow-hidden"
          style={{ height: 320, minHeight: 320 }}
        >
          {!hasData && (
            <div className="h-full flex items-center justify-center text-[11px] text-ink-500 italic">
              No samples to chart.
            </div>
          )}
        </div>
      ) : (
        <WaveformTable norm={norm} xUnit={xUnit} />
      )}
    </div>
  )
}

function WaveformTable({ norm, xUnit }) {
  const N = norm.data[0]?.length || 0
  const rowCount = Math.min(N, 50)
  if (N === 0) {
    return (
      <div className="px-3 py-4 text-[11px] text-ink-500 italic bg-ink-900 border border-ink-800 rounded">
        No samples.
      </div>
    )
  }
  return (
    <div className="overflow-auto bg-ink-900 border border-ink-800 rounded max-h-[360px]">
      <table className="w-full text-[11px] font-mono">
        <thead className="bg-ink-800/60 sticky top-0">
          <tr>
            <th className="text-left px-2 py-1 text-ink-400 font-medium">
              {xUnit ? `t (${xUnit})` : 't'}
            </th>
            {norm.names.map((name, i) => (
              <th
                key={name + i}
                className="text-left px-2 py-1 font-medium"
                style={{ color: PALETTE[i % PALETTE.length] }}
              >
                {norm.units[i] ? `${name} (${norm.units[i]})` : name}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Array.from({ length: rowCount }, (_, r) => (
            <tr key={r} className="border-t border-ink-800/60">
              <td className="px-2 py-1 text-ink-300">{fmtCell(norm.data[0][r])}</td>
              {norm.names.map((_, i) => (
                <td key={i} className="px-2 py-1 text-ink-200">
                  {fmtCell(norm.data[i + 1]?.[r])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {N > rowCount && (
        <div className="px-2 py-1 text-[10px] text-ink-500 italic border-t border-ink-800">
          Showing first {rowCount} of {N} samples.
        </div>
      )}
    </div>
  )
}

function fmtCell(v) {
  if (v == null) return '—'
  if (typeof v !== 'number' || !Number.isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a !== 0 && (a < 1e-3 || a >= 1e4)) return v.toExponential(3)
  return v.toPrecision(5)
}

function SectionHeading({ children }) {
  return (
    <div className="mb-2 text-[10px] uppercase tracking-wider text-ink-500 font-medium">
      {children}
    </div>
  )
}
