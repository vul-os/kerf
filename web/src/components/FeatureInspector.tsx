import { useState } from 'react'
import { Square, Minus, Circle, EyeOff, MessageSquare, Copy, X } from 'lucide-react'
import { findFeature } from '../lib/topology.js'
import type { Topology, TopologyPart, TopologyFace, TopologyEdge, TopologyVertex, FeatureKind, TopologyMapLike } from '../lib/topology.js'

const KIND_ICON = { face: Square, edge: Minus, vertex: Circle }

function fmt(n: number) {
  if (!isFinite(n)) return '—'
  return n.toFixed(3)
}
function fmtVec(v: [number, number, number] | null | undefined) {
  if (!v) return '—'
  return `(${fmt(v[0])}, ${fmt(v[1])}, ${fmt(v[2])})`
}
function rgbToHex([r, g, b]: [number, number, number]) {
  const c = (x: number) => Math.round(Math.max(0, Math.min(1, x)) * 255).toString(16).padStart(2, '0')
  return `#${c(r)}${c(g)}${c(b)}`
}
function hexToRgb(hex: string): [number, number, number] {
  const m = /^#?([0-9a-f]{6})$/i.exec(hex)
  if (!m) return [1, 1, 1]
  const n = parseInt(m[1], 16)
  return [((n >> 16) & 0xff) / 255, ((n >> 8) & 0xff) / 255, (n & 0xff) / 255]
}
function intColorToRgb(c: number | null | undefined): [number, number, number] {
  if (c == null) return [0.79, 0.66, 0.42]
  return [((c >> 16) & 0xff) / 255, ((c >> 8) & 0xff) / 255, (c & 0xff) / 255]
}

export interface FeatureSelection {
  partId: string
  kind: FeatureKind
  featureId: string
}

export interface Props {
  selection: FeatureSelection | null
  parts?: TopologyPart[]
  // Read-only: only .get() is used, so a plain Map and the store's TopologyMapLike both fit.
  topologies: TopologyMapLike
  onClose?: () => void
  onHidePart?: (partId: string) => void
  onReferenceInChat?: (partId: string, kind: FeatureKind, featureId: string) => void
  onRecolorPart?: (partId: string, rgb: [number, number, number]) => void
  isStepFile?: boolean
}

export default function FeatureInspector({
  selection,         // { partId, kind, featureId } | null
  parts,
  topologies,        // Map<partId, Topology>
  onClose,
  onHidePart,
  onReferenceInChat,
  onRecolorPart,
  isStepFile = false,
}: Props) {
  const [copied, setCopied] = useState(false)

  if (!selection) return null
  const { partId, kind, featureId } = selection
  const part = (parts || []).find((p) => p.id === partId)
  if (!part) return null
  const topology = topologies.get(partId)
  const feature = findFeature(topology, kind, featureId)
  if (!feature) return null

  const face = kind === 'face' ? (feature as TopologyFace) : null
  const edge = kind === 'edge' ? (feature as TopologyEdge) : null
  const vertex = kind === 'vertex' ? (feature as TopologyVertex) : null

  const Icon = KIND_ICON[kind] || Square

  function copyText(text: string) {
    navigator.clipboard?.writeText(text).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1200)
    })
  }

  return (
    <div className="absolute bottom-12 right-3 z-10 w-80 rounded-md border border-ink-700 bg-ink-900/90 backdrop-blur shadow-2xl text-ink-100 text-xs">
      <header className="flex items-center gap-2 px-3 py-2 border-b border-ink-800">
        <Icon size={13} className="text-kerf-300" />
        <span className="font-mono text-ink-200">{partId}</span>
        <span className="text-ink-600">·</span>
        <span className="font-mono text-ink-300">{featureId}</span>
        <div className="flex-1" />
        <button
          type="button"
          onClick={onClose}
          className="p-0.5 text-ink-400 hover:text-kerf-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70 rounded"
          title="Close (Esc)"
          aria-label="Close inspector"
        >
          <X size={13} />
        </button>
      </header>

      <div className="px-3 py-2 space-y-1.5">
        {face && (
          <>
            <Row label="Area"   value={`${fmt(face.area)} mm²`} />
            <Row label="Normal" value={fmtVec(face.normal)} />
            <Row label="Centroid" value={fmtVec(face.centroid)} />
            <Row label="Polygons" value={String(face.polygons.length)} />
          </>
        )}
        {edge && (
          <>
            <Row label="Length" value={`${fmt(edge.length)} mm`} />
            <Row label="A" value={fmtVec(edge.a)} />
            <Row label="B" value={fmtVec(edge.b)} />
          </>
        )}
        {vertex && (
          <>
            <Row label="Position" value={fmtVec(vertex.position)} />
            <Row label="On faces" value={vertex.faces.join(', ') || '—'} />
          </>
        )}
      </div>

      {/* Color picker (faces only, not for STEP) */}
      {kind === 'face' && !isStepFile && (
        <div className="px-3 py-2 border-t border-ink-800 flex items-center gap-2">
          <label className="text-ink-400">Part color</label>
          <input
            type="color"
            defaultValue={rgbToHex(intColorToRgb(part.color))}
            onChange={(e) => onRecolorPart?.(partId, hexToRgb(e.target.value))}
            className="w-7 h-6 rounded bg-ink-800 border border-ink-700 cursor-pointer focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
            title="Edit part color (mutates the source)"
            aria-label="Edit part color"
          />
          <span className="text-[10px] text-ink-500 font-mono">applies to whole part</span>
        </div>
      )}
      {kind === 'face' && isStepFile && (
        <div className="px-3 py-2 border-t border-ink-800 text-[10px] text-ink-500">
          Color editing is disabled for STEP files.
        </div>
      )}

      <div className="px-2 py-1.5 border-t border-ink-800 flex items-center gap-1">
        <button
          type="button"
          onClick={() => onHidePart?.(partId)}
          className="flex items-center gap-1 px-2 py-1 text-[11px] text-ink-300 hover:text-kerf-300 hover:bg-ink-800 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
          title="Hide the parent part"
        >
          <EyeOff size={11} /> Hide part
        </button>
        <button
          type="button"
          onClick={() => onReferenceInChat?.(partId, kind, featureId)}
          className="flex items-center gap-1 px-2 py-1 text-[11px] text-ink-300 hover:text-kerf-300 hover:bg-ink-800 rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
          title="Add a reference chip to the next chat message"
        >
          <MessageSquare size={11} /> Reference in chat
        </button>
        <button
          type="button"
          onClick={() => {
            const point: [number, number, number] | undefined =
              face   ? face.centroid :
              edge   ? [(edge.a[0] + edge.b[0]) / 2, (edge.a[1] + edge.b[1]) / 2, (edge.a[2] + edge.b[2]) / 2] :
              vertex ? vertex.position : undefined
            copyText(`${partId}#${featureId} ${fmtVec(point)}`)
          }}
          className="flex items-center gap-1 px-2 py-1 text-[11px] text-ink-300 hover:text-kerf-300 hover:bg-ink-800 rounded ml-auto"
          title="Copy coords to clipboard"
        >
          <Copy size={11} />
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2">
      <span className="w-16 text-ink-500 text-[10px] uppercase tracking-wider">{label}</span>
      <span className="font-mono text-ink-200 truncate">{value}</span>
    </div>
  )
}
