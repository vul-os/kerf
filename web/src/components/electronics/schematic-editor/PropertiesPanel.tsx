// PropertiesPanel.tsx — Right sidebar for selected component properties.

import { useCallback } from 'react'
import { PARTS_MAP } from './parts_library.js'

export interface Device {
  id: string
  partId: string
  x: number
  y: number
  props?: Record<string, string>
  label?: string
}

export interface Selected {
  type: 'part' | 'wire'
  id: string
}

// ── Field renderer ────────────────────────────────────────────────────────────

interface FieldProps {
  label: string
  value: string | undefined
  onChange: (value: string) => void
  suffix?: string
}

function Field({ label, value, onChange, suffix }: FieldProps) {
  return (
    <div className="flex flex-col gap-0.5">
      <label className="text-[10px] text-gray-500 uppercase tracking-wide">{label}</label>
      <div className="flex items-center gap-1">
        <input
          type="text"
          value={value ?? ''}
          onChange={(e) => onChange(e.target.value)}
          className="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1 text-xs text-gray-100 focus:outline-none focus:border-indigo-500 font-mono"
        />
        {suffix && <span className="text-[10px] text-gray-600">{suffix}</span>}
      </div>
    </div>
  )
}

// ── Property schema per part type ─────────────────────────────────────────────

interface PropSchemaEntry {
  key: string
  label: string
  suffix?: string
}

const PROP_SCHEMA: Record<string, PropSchemaEntry[]> = {
  R:       [{ key: 'resistance', label: 'Resistance', suffix: 'Ω' }],
  C:       [{ key: 'capacitance', label: 'Capacitance', suffix: 'F' }],
  L:       [{ key: 'inductance', label: 'Inductance', suffix: 'H' }],
  Diode:   [{ key: 'model', label: 'Model' }],
  LED:     [{ key: 'model', label: 'Model' }, { key: 'color', label: 'Color' }],
  Zener:   [{ key: 'model', label: 'Model' }, { key: 'bv', label: 'Vz', suffix: 'V' }],
  NMOS:    [{ key: 'model', label: 'Model' }, { key: 'W', label: 'Width', suffix: 'm' }, { key: 'L', label: 'Length', suffix: 'm' }],
  PMOS:    [{ key: 'model', label: 'Model' }, { key: 'W', label: 'Width', suffix: 'm' }, { key: 'L', label: 'Length', suffix: 'm' }],
  NPN:     [{ key: 'model', label: 'Model' }],
  PNP:     [{ key: 'model', label: 'Model' }],
  OpAmp:   [{ key: 'model', label: 'Model' }, { key: 'Av', label: 'Open-loop gain' }],
  VSource: [{ key: 'dc', label: 'DC voltage', suffix: 'V' }, { key: 'ac', label: 'AC amplitude', suffix: 'V' }, { key: 'type', label: 'Type' }],
  ISource: [{ key: 'dc', label: 'DC current', suffix: 'A' }, { key: 'type', label: 'Type' }],
  GND:     [{ key: 'net', label: 'Net name' }],
  Probe:   [{ key: 'label', label: 'Label' }, { key: 'kind', label: 'Kind (voltage/current)' }],
}

// ── Main component ────────────────────────────────────────────────────────────

export interface PropertiesPanelProps {
  selected: Selected | null
  devices: Device[]
  onUpdateProps?: (deviceId: string, newProps: Record<string, string>) => void
  onUpdateLabel?: (deviceId: string, newLabel: string) => void
  onDelete?: (id: string, type: 'part' | 'wire') => void
}

export default function PropertiesPanel({ selected, devices, onUpdateProps, onUpdateLabel, onDelete }: PropertiesPanelProps) {
  const handlePropChange = useCallback((deviceId: string, key: string, value: string) => {
    const dev = devices.find((d) => d.id === deviceId)
    if (!dev) return
    onUpdateProps?.(deviceId, { ...dev.props, [key]: value })
  }, [devices, onUpdateProps])

  if (!selected) {
    return (
      <div
        className="flex flex-col h-full bg-[#0b1120] border-l border-white/10 items-center justify-center"
        style={{ width: 220, minWidth: 220 }}
        data-testid="properties-panel"
      >
        <p className="text-xs text-gray-600 px-4 text-center leading-relaxed">
          Select a component to view and edit its properties
        </p>
      </div>
    )
  }

  if (selected.type === 'wire') {
    return (
      <div
        className="flex flex-col h-full bg-[#0b1120] border-l border-white/10 p-3 gap-3"
        style={{ width: 220, minWidth: 220 }}
        data-testid="properties-panel"
      >
        <div className="border-b border-white/10 pb-2">
          <span className="text-xs font-semibold text-gray-300">Wire</span>
          <p className="text-[10px] text-gray-600 mt-0.5 font-mono break-all">{selected.id}</p>
        </div>
        <button
          onClick={() => onDelete?.(selected.id, 'wire')}
          className="w-full px-3 py-1.5 text-xs rounded bg-red-900/30 text-red-400 border border-red-700/40 hover:bg-red-800/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          Delete Wire
        </button>
      </div>
    )
  }

  // Part selected
  const dev = devices.find((d) => d.id === selected.id)
  if (!dev) return null

  const partDef = PARTS_MAP[dev.partId]
  const schema  = PROP_SCHEMA[dev.partId] ?? []

  return (
    <div
      className="flex flex-col h-full bg-[#0b1120] border-l border-white/10 p-3 gap-3 overflow-y-auto"
      style={{ width: 220, minWidth: 220 }}
      data-testid="properties-panel"
    >
      {/* Header */}
      <div className="border-b border-white/10 pb-2">
        <span className="text-xs font-semibold text-gray-300">{partDef?.label ?? dev.partId}</span>
        <p className="text-[10px] text-gray-600 mt-0.5 font-mono">{dev.id}</p>
      </div>

      {/* Ref designator label */}
      <Field
        label="Ref Designator"
        value={dev.label}
        onChange={(v) => onUpdateLabel?.(dev.id, v)}
      />

      {/* Part-specific props */}
      {schema.map(({ key, label, suffix }) => (
        <Field
          key={key}
          label={label}
          suffix={suffix}
          value={dev.props?.[key] ?? ''}
          onChange={(v) => handlePropChange(dev.id, key, v)}
        />
      ))}

      {/* Position (read-only) */}
      <div className="flex gap-2">
        <div className="flex-1">
          <label className="text-[10px] text-gray-600 uppercase tracking-wide">X (mil)</label>
          <p className="text-xs text-gray-500 font-mono mt-0.5">{dev.x}</p>
        </div>
        <div className="flex-1">
          <label className="text-[10px] text-gray-600 uppercase tracking-wide">Y (mil)</label>
          <p className="text-xs text-gray-500 font-mono mt-0.5">{dev.y}</p>
        </div>
      </div>

      <div className="mt-auto">
        <button
          onClick={() => onDelete?.(dev.id, 'part')}
          className="w-full px-3 py-1.5 text-xs rounded bg-red-900/30 text-red-400 border border-red-700/40 hover:bg-red-800/40 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
        >
          Delete Component
        </button>
      </div>
    </div>
  )
}
