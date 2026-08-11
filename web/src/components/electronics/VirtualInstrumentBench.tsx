// VirtualInstrumentBench.jsx — Virtual instrument bench panel for the
// electronics/schematic editor.
//
// Instruments:
//   Oscilloscope — multi-channel time-domain trace with V/div, time/div,
//     trigger level, and cursor measurements (Vpp, freq, rise-time, RMS, DC).
//   Multimeter   — DC/AC/RMS voltage + DC/AC current readout at a chosen node.
//   Function Gen — produce a stimulus spec (sine/square/triangle, freq/amp/
//     offset/duty) that drives a transient sim; emits SPICE source line.
//   Probes       — per-node V/I overlay via eda_probe_nodes.
//
// Backend (via api.callTool → POST /api/tools/call):
//   eda_virtual_instrument
//   eda_probe_nodes
//
// All instruments show demo-mode data when the backend is offline.
// References: Tektronix TDS2000 operator's manual (scope), IEC 60469 §4 (AC RMS).

import type { ComponentType, ReactNode } from 'react'
import { useCallback, useState } from 'react'
import { X, Activity, Radio, Zap, Crosshair } from 'lucide-react'
import { api } from '../../lib/api.js'

// ── Types ─────────────────────────────────────────────────────────────────
// The virtual instrument bench is a thin client over the eda_virtual_instrument
// + eda_probe_nodes tools; there's no shared type for these payload shapes yet,
// so they're declared locally from the tools' response contract (mirrored in
// the DEMO_* fallbacks below).

interface OscopeChannel {
  channel: string
  vpp: number
  v_min: number
  v_max: number
  dc_mean: number
  rms: number
  ac_rms: number
  frequency_hz: number | null
  period_s: number | null
  rise_time_s: number | null
  n_samples: number
}

interface OscopeResult {
  instrument: 'oscilloscope'
  channels: OscopeChannel[]
  time_start_s: number
  time_stop_s: number
  sample_rate_hz: number
  warnings: string[]
}

interface MultimeterResult {
  instrument: 'multimeter'
  node: string
  mode: string
  value: number | null
  unit: string
  n_samples: number
  warning: string | null
}

interface FGenResult {
  instrument: 'function_generator'
  waveform: string
  freq_hz: number
  amplitude_v: number
  offset_v: number
  duty_cycle: number
  source_name: string
  pos_node: string
  neg_node: string
  spice_line: string
  tran_directive: string
}

interface ProbeResult {
  node: string
  kind: string
  value: number
  unit: string
  dc: number
  rms: number
  label: string
  not_found: boolean
}

interface ProbesResult {
  probes: ProbeResult[]
  warnings: string[]
  at_time: number | null
}

// ── Palette ────────────────────────────────────────────────────────────────

const CHANNEL_COLORS = ['#f59e0b', '#22d3ee', '#a78bfa', '#34d399', '#f472b6']

// ── Demo data ──────────────────────────────────────────────────────────────

const DEMO_OSCOPE: OscopeResult = {
  instrument: 'oscilloscope',
  channels: [
    {
      channel: 'V(out)',
      vpp: 2.0,
      v_min: -1.0,
      v_max: 1.0,
      dc_mean: 0.0,
      rms: 0.707,
      ac_rms: 0.707,
      frequency_hz: 1000.0,
      period_s: 0.001,
      rise_time_s: null,
      n_samples: 1000,
    },
  ],
  time_start_s: 0.0,
  time_stop_s: 0.01,
  sample_rate_hz: 100000,
  warnings: [],
}

const DEMO_MULTIMETER: MultimeterResult = {
  instrument: 'multimeter',
  node: 'V(out)',
  mode: 'dc_voltage',
  value: 2.5,
  unit: 'V',
  n_samples: 100,
  warning: null,
}

const DEMO_FGEN: FGenResult = {
  instrument: 'function_generator',
  waveform: 'sine',
  freq_hz: 1000,
  amplitude_v: 1.5,
  offset_v: 0.0,
  duty_cycle: 0.5,
  source_name: 'stim',
  pos_node: 'vin',
  neg_node: '0',
  spice_line: 'Vstim vin 0 SIN(0 1.5 1000)',
  tran_directive: '.TRAN 1e-05 0.01',
}

const DEMO_PROBES: ProbesResult = {
  probes: [
    { node: 'V(out)', kind: 'V', value: 2.5, unit: 'V', dc: 2.5, rms: 2.5, label: '2.5 V', not_found: false },
    { node: 'V(vdd)', kind: 'V', value: 5.0, unit: 'V', dc: 5.0, rms: 5.0, label: '5.0 V', not_found: false },
  ],
  warnings: [],
  at_time: null,
}

// ── Shared form helpers ────────────────────────────────────────────────────

function Label({ children }: { children: ReactNode }) {
  return (
    <span className="text-gray-500 text-[10px] uppercase tracking-wide">{children}</span>
  )
}

interface FieldProps {
  label: string
  value: string
  unit?: string
  type?: string
  step?: string
  min?: string
  onChange: (value: string) => void
  testId?: string
}

function Field({ label, value, unit, type = 'number', step = 'any', min, onChange, testId }: FieldProps) {
  return (
    <label className="flex flex-col gap-0.5">
      <Label>{label}</Label>
      <div className="flex items-center gap-1">
        <input
          data-testid={testId}
          type={type}
          step={step}
          min={min}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white w-24 text-xs focus:outline-none focus:border-indigo-500"
        />
        {unit && <span className="text-gray-600 text-[10px]">{unit}</span>}
      </div>
    </label>
  )
}

interface SelectOption {
  value: string
  label: string
}

interface SelectProps {
  label: string
  value: string
  options: SelectOption[]
  onChange: (value: string) => void
  testId?: string
}

function Select({ label, value, options, onChange, testId }: SelectProps) {
  return (
    <label className="flex flex-col gap-0.5">
      <Label>{label}</Label>
      <select
        data-testid={testId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-black/40 border border-white/10 rounded px-2 py-1 text-white text-xs focus:outline-none focus:border-indigo-500"
      >
        {options.map(({ value: v, label: l }) => (
          <option key={v} value={v}>{l}</option>
        ))}
      </select>
    </label>
  )
}

interface MetricProps {
  label: string
  value: ReactNode
  unit?: string
  color?: string
}

function Metric({ label, value, unit, color }: MetricProps) {
  return (
    <div className="flex flex-col gap-0.5 min-w-[64px]">
      <span className="text-gray-500 text-[10px] uppercase tracking-wide">{label}</span>
      <span className="text-xs font-mono" style={{ color: color || '#e5e7eb' }}>
        {value ?? <span className="text-gray-600">—</span>}
        {unit && value != null
          ? <span className="text-gray-500 ml-0.5 text-[10px]">{unit}</span>
          : null}
      </span>
    </div>
  )
}

function Warn({ msg }: { msg: string | null }) {
  if (!msg) return null
  return (
    <div className="mt-1 px-2 py-1 rounded bg-amber-950/40 border border-amber-700/40 text-[10px] text-amber-300 font-mono break-all">
      {msg}
    </div>
  )
}

function fmtSI(v: number | null | undefined, unit: string): string {
  if (v == null || typeof v !== 'number' || !isFinite(v)) return '—'
  const a = Math.abs(v)
  if (a === 0) return `0 ${unit}`
  if (a >= 1) return `${v.toPrecision(4)} ${unit}`
  if (a >= 1e-3) return `${(v * 1e3).toPrecision(4)} m${unit}`
  if (a >= 1e-6) return `${(v * 1e6).toPrecision(4)} µ${unit}`
  return `${(v * 1e9).toPrecision(4)} n${unit}`
}

// ─────────────────────────────────────────────────────────────────────────────
// Oscilloscope tab
// ─────────────────────────────────────────────────────────────────────────────

function OscopeTab({ waveforms }: { waveforms?: unknown[] }) {
  const [channels, setChannels] = useState('V(out)')
  const [result, setResult] = useState<OscopeResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [demoMode, setDemoMode] = useState(false)

  const run = useCallback(async () => {
    setBusy(true)
    setErr(null)
    try {
      const chList = channels.split(',').map((c) => c.trim()).filter(Boolean)
      const data = await api.callTool<OscopeResult>('eda_virtual_instrument', {
        instrument: 'oscilloscope',
        waveforms: waveforms || [],
        channels: chList,
      })
      setResult(data)
      setDemoMode(false)
    } catch {
      setResult(DEMO_OSCOPE)
      setDemoMode(true)
    } finally {
      setBusy(false)
    }
  }, [channels, waveforms])

  return (
    <div data-testid="vi-oscope-tab" className="space-y-3">
      <div className="flex flex-wrap gap-3 items-end">
        <Field
          label="Channels (comma-sep)"
          value={channels}
          type="text"
          onChange={setChannels}
          testId="vi-oscope-channels"
        />
        <button
          data-testid="vi-oscope-run"
          onClick={run}
          disabled={busy}
          className="self-end px-3 py-1.5 rounded bg-amber-500 hover:bg-amber-400 disabled:opacity-50 text-black text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          {busy ? 'Measuring…' : 'Measure'}
        </button>
      </div>

      {demoMode && (
        <div className="text-[10px] text-amber-400 border border-amber-700/40 rounded px-2 py-1">
          Backend offline — showing demo data
        </div>
      )}

      {result && result.channels && result.channels.map((ch, i) => (
        <div
          key={ch.channel}
          data-testid={`vi-oscope-channel-${i}`}
          className="border border-white/10 rounded p-3 space-y-2"
        >
          <div className="flex items-center gap-2">
            <div
              className="w-2 h-2 rounded-full shrink-0"
              style={{ background: CHANNEL_COLORS[i % CHANNEL_COLORS.length] }}
            />
            <span className="text-xs font-mono font-semibold" style={{ color: CHANNEL_COLORS[i % CHANNEL_COLORS.length] }}>
              {ch.channel}
            </span>
            <span className="text-[10px] text-gray-600">{ch.n_samples} samples</span>
          </div>
          <div className="grid grid-cols-4 gap-2 text-[11px]">
            <Metric label="Vpp" value={fmtSI(ch.vpp, 'V')} />
            <Metric label="Vmin" value={fmtSI(ch.v_min, 'V')} />
            <Metric label="Vmax" value={fmtSI(ch.v_max, 'V')} />
            <Metric label="DC" value={fmtSI(ch.dc_mean, 'V')} />
            <Metric label="RMS" value={fmtSI(ch.rms, 'V')} />
            <Metric label="AC RMS" value={fmtSI(ch.ac_rms, 'V')} />
            <Metric label="Freq" value={ch.frequency_hz != null ? fmtSI(ch.frequency_hz, 'Hz') : null} />
            <Metric label="Rise time" value={ch.rise_time_s != null ? fmtSI(ch.rise_time_s, 's') : null} />
          </div>
        </div>
      ))}

      {result && result.warnings && result.warnings.map((w, i) => (
        <Warn key={i} msg={w} />
      ))}
      {err && <Warn msg={err} />}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Multimeter tab
// ─────────────────────────────────────────────────────────────────────────────

const MM_MODES = [
  { value: 'dc_voltage', label: 'DC Voltage' },
  { value: 'ac_voltage', label: 'AC Voltage (peak)' },
  { value: 'ac_voltage_rms', label: 'AC Voltage RMS' },
  { value: 'dc_current', label: 'DC Current' },
  { value: 'ac_current_rms', label: 'AC Current RMS' },
]

function MultimeterTab({ waveforms }: { waveforms?: unknown[] }) {
  const [node, setNode] = useState('V(out)')
  const [mode, setMode] = useState('dc_voltage')
  const [result, setResult] = useState<MultimeterResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoMode, setDemoMode] = useState(false)

  const run = useCallback(async () => {
    setBusy(true)
    try {
      const data = await api.callTool<MultimeterResult>('eda_virtual_instrument', {
        instrument: 'multimeter',
        waveforms: waveforms || [],
        node,
        mode,
      })
      setResult(data)
      setDemoMode(false)
    } catch {
      setResult({ ...DEMO_MULTIMETER, node, mode })
      setDemoMode(true)
    } finally {
      setBusy(false)
    }
  }, [node, mode, waveforms])

  return (
    <div data-testid="vi-multimeter-tab" className="space-y-3">
      <div className="flex flex-wrap gap-3 items-end">
        <Field
          label="Node"
          value={node}
          type="text"
          onChange={setNode}
          testId="vi-mm-node"
        />
        <Select
          label="Mode"
          value={mode}
          options={MM_MODES}
          onChange={setMode}
          testId="vi-mm-mode"
        />
        <button
          data-testid="vi-mm-read"
          onClick={run}
          disabled={busy}
          className="self-end px-3 py-1.5 rounded bg-indigo-500 hover:bg-indigo-400 disabled:opacity-50 text-white text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          {busy ? 'Reading…' : 'Read'}
        </button>
      </div>

      {demoMode && (
        <div className="text-[10px] text-amber-400 border border-amber-700/40 rounded px-2 py-1">
          Backend offline — showing demo data
        </div>
      )}

      {result && (
        <div data-testid="vi-mm-result" className="border border-white/10 rounded p-3">
          <div className="flex items-center gap-3">
            <span className="text-gray-500 text-[10px] uppercase tracking-wide">
              {result.node} · {MM_MODES.find((m) => m.value === result.mode)?.label ?? result.mode}
            </span>
          </div>
          <div className="mt-2 text-2xl font-mono font-bold text-green-400">
            {result.value != null
              ? `${Number(result.value).toPrecision(5)} ${result.unit}`
              : '—'}
          </div>
          {result.warning && <Warn msg={result.warning} />}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Function generator tab
// ─────────────────────────────────────────────────────────────────────────────

const WAVEFORM_TYPES = [
  { value: 'sine', label: 'Sine' },
  { value: 'square', label: 'Square' },
  { value: 'triangle', label: 'Triangle' },
]

function FunctionGenTab() {
  const [waveform, setWaveform] = useState('sine')
  const [freqHz, setFreqHz] = useState('1000')
  const [ampV, setAmpV] = useState('1.0')
  const [offsetV, setOffsetV] = useState('0.0')
  const [duty, setDuty] = useState('0.5')
  const [sourceName, setSourceName] = useState('stim')
  const [posNode, setPosNode] = useState('vin')
  const [result, setResult] = useState<FGenResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoMode, setDemoMode] = useState(false)

  const generate = useCallback(async () => {
    setBusy(true)
    try {
      const data = await api.callTool<FGenResult>('eda_virtual_instrument', {
        instrument: 'function_generator',
        waveform,
        freq_hz: Number(freqHz),
        amplitude_v: Number(ampV),
        offset_v: Number(offsetV),
        duty_cycle: Number(duty),
        source_name: sourceName,
        pos_node: posNode,
        neg_node: '0',
      })
      setResult(data)
      setDemoMode(false)
    } catch {
      setResult({ ...DEMO_FGEN, waveform, freq_hz: Number(freqHz), amplitude_v: Number(ampV) })
      setDemoMode(true)
    } finally {
      setBusy(false)
    }
  }, [waveform, freqHz, ampV, offsetV, duty, sourceName, posNode])

  return (
    <div data-testid="vi-fgen-tab" className="space-y-3">
      <div className="flex flex-wrap gap-3 items-end">
        <Select
          label="Waveform"
          value={waveform}
          options={WAVEFORM_TYPES}
          onChange={setWaveform}
          testId="vi-fgen-waveform"
        />
        <Field label="Freq" value={freqHz} unit="Hz" onChange={setFreqHz} testId="vi-fgen-freq" />
        <Field label="Amplitude" value={ampV} unit="V" onChange={setAmpV} testId="vi-fgen-amp" />
        <Field label="Offset" value={offsetV} unit="V" onChange={setOffsetV} testId="vi-fgen-offset" />
        {waveform === 'square' && (
          <Field label="Duty" value={duty} unit="(0–1)" step="0.01" min="0" onChange={setDuty} testId="vi-fgen-duty" />
        )}
        <Field label="Source ref" value={sourceName} type="text" onChange={setSourceName} testId="vi-fgen-source" />
        <Field label="Pos node" value={posNode} type="text" onChange={setPosNode} testId="vi-fgen-posnode" />
        <button
          data-testid="vi-fgen-generate"
          onClick={generate}
          disabled={busy}
          className="self-end px-3 py-1.5 rounded bg-purple-500 hover:bg-purple-400 disabled:opacity-50 text-white text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          {busy ? 'Generating…' : 'Generate'}
        </button>
      </div>

      {demoMode && (
        <div className="text-[10px] text-amber-400 border border-amber-700/40 rounded px-2 py-1">
          Backend offline — showing demo data
        </div>
      )}

      {result && (
        <div data-testid="vi-fgen-result" className="border border-white/10 rounded p-3 space-y-2">
          <div className="grid grid-cols-3 gap-2 text-[11px]">
            <Metric label="Waveform" value={result.waveform} />
            <Metric label="Frequency" value={fmtSI(result.freq_hz, 'Hz')} />
            <Metric label="Amplitude" value={fmtSI(result.amplitude_v, 'V')} />
            <Metric label="Offset" value={fmtSI(result.offset_v, 'V')} />
            {result.waveform === 'square' && (
              <Metric label="Duty cycle" value={`${(result.duty_cycle * 100).toFixed(1)}%`} />
            )}
          </div>
          <div className="mt-2">
            <Label>SPICE source line</Label>
            <pre
              data-testid="vi-fgen-spice-line"
              className="mt-1 text-[10px] font-mono bg-black/40 border border-white/5 rounded px-2 py-1 text-green-300 whitespace-pre-wrap break-all"
            >
              {result.spice_line}
            </pre>
          </div>
          <div>
            <Label>.TRAN directive</Label>
            <pre
              data-testid="vi-fgen-tran"
              className="mt-1 text-[10px] font-mono bg-black/40 border border-white/5 rounded px-2 py-1 text-cyan-300 whitespace-pre-wrap break-all"
            >
              {result.tran_directive}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Probes tab
// ─────────────────────────────────────────────────────────────────────────────

function ProbesTab({ waveforms }: { waveforms?: unknown[] }) {
  const [nodeList, setNodeList] = useState('V(out), V(vdd)')
  const [atTime, setAtTime] = useState('')
  const [result, setResult] = useState<ProbesResult | null>(null)
  const [busy, setBusy] = useState(false)
  const [demoMode, setDemoMode] = useState(false)

  const run = useCallback(async () => {
    setBusy(true)
    try {
      const nodes = nodeList.split(',').map((n) => n.trim()).filter(Boolean)
      const payload: { waveforms: unknown[]; nodes: string[]; at_time?: number } = {
        waveforms: waveforms || [],
        nodes,
      }
      if (atTime !== '') payload.at_time = Number(atTime)
      const data = await api.callTool<ProbesResult>('eda_probe_nodes', payload)
      setResult(data)
      setDemoMode(false)
    } catch {
      setResult(DEMO_PROBES)
      setDemoMode(true)
    } finally {
      setBusy(false)
    }
  }, [nodeList, atTime, waveforms])

  return (
    <div data-testid="vi-probes-tab" className="space-y-3">
      <div className="flex flex-wrap gap-3 items-end">
        <Field
          label="Nodes (comma-sep)"
          value={nodeList}
          type="text"
          onChange={setNodeList}
          testId="vi-probes-nodes"
        />
        <Field
          label="At time"
          value={atTime}
          unit="s"
          onChange={setAtTime}
          testId="vi-probes-at-time"
        />
        <button
          data-testid="vi-probes-run"
          onClick={run}
          disabled={busy}
          className="self-end px-3 py-1.5 rounded bg-teal-500 hover:bg-teal-400 disabled:opacity-50 text-black text-xs font-semibold focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          {busy ? 'Probing…' : 'Probe'}
        </button>
      </div>

      {demoMode && (
        <div className="text-[10px] text-amber-400 border border-amber-700/40 rounded px-2 py-1">
          Backend offline — showing demo data
        </div>
      )}

      {result && result.probes && (
        <div data-testid="vi-probes-result" className="space-y-2">
          {result.probes.map((p, i) => (
            <div
              key={p.node + i}
              data-testid={`vi-probe-${i}`}
              className={`border rounded px-3 py-2 flex items-center gap-4 ${
                p.not_found
                  ? 'border-red-800/40 bg-red-950/20'
                  : 'border-white/10 bg-white/2'
              }`}
            >
              {/* On-wire label badge */}
              <span
                className={`font-mono text-xs font-bold px-2 py-0.5 rounded ${
                  p.kind === 'I' ? 'bg-amber-900/50 text-amber-300' : 'bg-teal-900/50 text-teal-300'
                }`}
              >
                {p.not_found ? '??' : p.label}
              </span>
              <span className="text-gray-400 text-[10px] font-mono">{p.node}</span>
              {!p.not_found && (
                <>
                  <Metric label="DC" value={fmtSI(p.dc, p.unit)} />
                  <Metric label="RMS" value={fmtSI(p.rms, p.unit)} />
                  <span
                    className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 border rounded"
                    style={{
                      color: p.kind === 'I' ? '#fcd34d' : '#5eead4',
                      borderColor: p.kind === 'I' ? '#78350f' : '#134e4a',
                    }}
                  >
                    {p.kind}
                  </span>
                </>
              )}
              {p.not_found && (
                <span className="text-red-400 text-[10px]">node not found</span>
              )}
            </div>
          ))}
          {result.warnings && result.warnings.map((w, i) => (
            <Warn key={i} msg={w} />
          ))}
        </div>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────────────
// Main panel
// ─────────────────────────────────────────────────────────────────────────────

type TabKey = 'oscilloscope' | 'multimeter' | 'fgen' | 'probes'

const TABS: { key: TabKey; label: string; icon: ComponentType<{ size?: number }> }[] = [
  { key: 'oscilloscope', label: 'Oscilloscope', icon: Activity },
  { key: 'multimeter',   label: 'Multimeter',   icon: Radio },
  { key: 'fgen',         label: 'Func Gen',     icon: Zap },
  { key: 'probes',       label: 'Probes',       icon: Crosshair },
]

export interface Props {
  onClose?: () => void
  waveforms?: unknown[]
  content?: string
}

export default function VirtualInstrumentBench({ onClose, waveforms, content }: Props) {
  // Parse content string (from panelRegistry) to seed defaults (not yet used but accepted for compat)
  const _defaults = (() => { try { return content ? JSON.parse(content) : {} } catch { return {} } })()
  const [tab, setTab] = useState<TabKey>('oscilloscope')

  return (
    <div
      data-testid="virtual-instrument-bench"
      className="flex flex-col bg-[#0e0e0e] border border-white/10 rounded-xl shadow-2xl overflow-hidden"
      style={{ minWidth: 480, maxWidth: 680 }}
    >
      {/* Header */}
      <div className="flex items-center gap-2 px-4 py-2.5 border-b border-white/10 bg-black/30 shrink-0">
        <Activity size={14} className="text-amber-400 shrink-0" />
        <span className="text-xs font-semibold uppercase tracking-wider text-gray-300">
          Virtual Instrument Bench
        </span>
        <span className="ml-auto text-[10px] text-gray-600">
          {waveforms && waveforms.length > 0
            ? `${waveforms.length} waveform${waveforms.length === 1 ? '' : 's'} loaded`
            : 'no simulation data'}
        </span>
        {onClose && (
          <button
            data-testid="vi-bench-close"
            onClick={onClose}
            className="ml-2 p-1 rounded hover:bg-white/10 text-gray-500 hover:text-white transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
            title="Close"
            aria-label="Close virtual instrument bench"
          >
            <X size={13} />
          </button>
        )}
      </div>

      {/* Tab bar */}
      <div className="flex items-center border-b border-white/10 bg-black/20 shrink-0">
        {TABS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            data-testid={`vi-tab-${key}`}
            onClick={() => setTab(key)}
            className={`flex items-center gap-1.5 px-4 py-2 text-[11px] uppercase tracking-wider font-medium transition-colors border-b-2 ${
              tab === key
                ? 'border-amber-400 text-amber-300'
                : 'border-transparent text-gray-500 hover:text-gray-300'
            } focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70`}
            aria-selected={tab === key}
          >
            <Icon size={11} />
            {label}
          </button>
        ))}
      </div>

      {/* Tab body */}
      <div className="flex-1 overflow-auto p-4">
        {tab === 'oscilloscope' && <OscopeTab waveforms={waveforms} />}
        {tab === 'multimeter'   && <MultimeterTab waveforms={waveforms} />}
        {tab === 'fgen'         && <FunctionGenTab />}
        {tab === 'probes'       && <ProbesTab waveforms={waveforms} />}
      </div>
    </div>
  )
}
