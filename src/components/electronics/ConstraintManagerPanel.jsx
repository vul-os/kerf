// ConstraintManagerPanel.jsx — Allegro-style Constraint Manager spreadsheet UI.
//
// Provides an editable spreadsheet grid where rows = net-classes or per-net
// overrides and columns = constraint properties.  Loads via constraint_table_get
// and commits edits via constraint_table_set — flipping "partial" → "yes".
//
// Backend contracts:
//   POST /api/llm-tools/constraint_table_get  {circuit_json}
//   POST /api/llm-tools/constraint_table_set  {circuit_json, edits}
//
// References: Allegro Constraint Manager Design Guide; IPC-2221B trace rules.
//
// Props:
//   circuitJson — CircuitJSON board object (defaults to DEMO_BOARD)
//   onClose     — () => void

import { useCallback, useEffect, useRef, useState } from 'react'
import { Table2, CheckCircle2, AlertTriangle, X, RefreshCw, Plus, Save } from 'lucide-react'

// ── Demo board ────────────────────────────────────────────────────────────────

const DEMO_BOARD = {
  type: 'pcb_board',
  width: 100,
  height: 80,
  net_classes: [
    { name: 'USB3', trace_width_mm: 0.22, clearance_mm: 0.18, via_diameter_mm: 0.50, via_drill_mm: 0.25,
      target_impedance_ohms: 90, via_type: 'blind', length_match_group: 'USB3_PAIRS' },
  ],
  net_rules: {
    GND: { trace_width_mm: 0.8, clearance_mm: 0.2 },
  },
  net_class_assignments: {
    GND: 'Default',
    VCC: 'Power',
    CLK_P: 'HighSpeed',
    CLK_N: 'HighSpeed',
    USB_DP: 'USB3',
    USB_DN: 'USB3',
  },
}

// ── Column config ─────────────────────────────────────────────────────────────

const DISPLAY_COLUMNS = [
  { key: 'name',                  label: 'Name',        width: 130, readonly: true,  type: 'text'   },
  { key: 'kind',                  label: 'Kind',        width: 80,  readonly: true,  type: 'badge'  },
  { key: 'trace_width_mm',        label: 'W (mm)',      width: 72,  readonly: false, type: 'number' },
  { key: 'clearance_mm',          label: 'Clr (mm)',    width: 72,  readonly: false, type: 'number' },
  { key: 'via_diameter_mm',       label: 'Via ⌀ (mm)',  width: 80,  readonly: false, type: 'number' },
  { key: 'via_drill_mm',          label: 'Drill (mm)',  width: 76,  readonly: false, type: 'number' },
  { key: 'target_impedance_ohms', label: 'Z₀ (Ω)',      width: 68,  readonly: false, type: 'number' },
  { key: 'length_match_group',    label: 'LenMatch',    width: 100, readonly: false, type: 'text'   },
  { key: 'via_type',              label: 'Via Type',    width: 80,  readonly: false, type: 'select',
    options: ['', 'through', 'blind', 'buried', 'micro'] },
]

// ── Helpers ───────────────────────────────────────────────────────────────────

async function apiPost(endpoint, body) {
  try {
    const r = await fetch(`/api/llm-tools/${endpoint}`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
    return r.ok ? r.json() : { error: `HTTP ${r.status}` }
  } catch (e) {
    return { error: e.message }
  }
}

function fmt(val, type) {
  if (val == null || val === '') return '—'
  if (type === 'number') return Number(val).toFixed(val < 1 ? 2 : 1)
  return String(val)
}

// ── Kind badge ────────────────────────────────────────────────────────────────

function KindBadge({ kind }) {
  return (
    <span className={`text-[10px] px-1.5 py-0.5 rounded font-mono
      ${kind === 'net_class'
        ? 'bg-blue-900/40 text-blue-300'
        : 'bg-green-900/40 text-green-300'}`}>
      {kind === 'net_class' ? 'class' : 'net'}
    </span>
  )
}

// ── Editable cell ─────────────────────────────────────────────────────────────

function Cell({ col, value, pendingValue, onEdit, edited }) {
  const [editing, setEditing] = useState(false)
  const [draft,   setDraft]   = useState('')
  const inputRef = useRef(null)

  const start = () => {
    if (col.readonly) return
    setDraft(value ?? '')
    setEditing(true)
    setTimeout(() => inputRef.current?.select(), 0)
  }

  const commit = () => {
    setEditing(false)
    let v = draft.trim()
    if (v === '' || v === '—') { onEdit(null); return }
    if (col.type === 'number') {
      const n = parseFloat(v)
      if (!isNaN(n)) onEdit(n)
    } else {
      onEdit(v)
    }
  }

  const cancel = () => setEditing(false)

  const display = pendingValue !== undefined ? pendingValue : value

  if (col.type === 'badge') {
    return (
      <td className="px-2 py-1 text-center" style={{ width: col.width, minWidth: col.width }}>
        <KindBadge kind={display} />
      </td>
    )
  }

  if (editing && col.type === 'select') {
    return (
      <td className="px-1 py-0.5" style={{ width: col.width, minWidth: col.width }}>
        <select
          autoFocus
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          className="w-full bg-gray-800 border border-blue-500 rounded px-1 py-0.5 text-[11px]
                     text-gray-200 focus:outline-none">
          {col.options.map(o => <option key={o} value={o}>{o || '—'}</option>)}
        </select>
      </td>
    )
  }

  if (editing) {
    return (
      <td className="px-1 py-0.5" style={{ width: col.width, minWidth: col.width }}>
        <input
          ref={inputRef}
          autoFocus
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onBlur={commit}
          onKeyDown={e => { if (e.key === 'Enter') commit(); if (e.key === 'Escape') cancel() }}
          className="w-full bg-gray-800 border border-blue-500 rounded px-1 py-0.5 text-[11px]
                     font-mono text-gray-200 focus:outline-none"
        />
      </td>
    )
  }

  return (
    <td
      onClick={col.readonly ? undefined : start}
      className={`px-2 py-1 text-[11px] text-right font-mono
        ${col.readonly ? 'text-gray-400 cursor-default' : 'cursor-pointer hover:bg-blue-900/20'}
        ${edited ? 'text-blue-300 bg-blue-900/10' : 'text-gray-300'}`}
      style={{ width: col.width, minWidth: col.width }}
      title={col.readonly ? undefined : 'Click to edit'}
    >
      {col.type === 'text'
        ? (display != null ? String(display) : '—')
        : fmt(display, col.type)}
    </td>
  )
}

// ── Row ───────────────────────────────────────────────────────────────────────

function Row({ row, pending, onCellEdit }) {
  return (
    <tr className="border-b border-white/5 hover:bg-white/[0.02] transition-colors">
      {DISPLAY_COLUMNS.map(col => {
        const edited = pending?.[col.key] !== undefined
        return (
          <Cell
            key={col.key}
            col={col}
            value={row[col.key]}
            pendingValue={pending?.[col.key]}
            edited={edited}
            onEdit={val => onCellEdit(row.name, row.kind, col.key, val)}
          />
        )
      })}
    </tr>
  )
}

// ── Main panel ────────────────────────────────────────────────────────────────

export default function ConstraintManagerPanel({ circuitJson: circuitJsonProp, onClose }) {
  const [circuitJson, setCircuitJson] = useState(circuitJsonProp ?? DEMO_BOARD)
  const [rows,        setRows]        = useState([])
  const [loading,     setLoading]     = useState(false)
  const [error,       setError]       = useState(null)
  // pending[rowName][col] = newValue
  const [pending, setPending]         = useState({})
  // last commit result
  const [commitResult, setCommitResult] = useState(null)
  // new net/class form
  const [addName, setAddName]         = useState('')
  const [addKind, setAddKind]         = useState('net_class')

  const loadTable = useCallback(async (cj) => {
    setLoading(true)
    setError(null)
    const r = await apiPost('constraint_table_get', { circuit_json: cj ?? circuitJson })
    setLoading(false)
    if (r.error) { setError(r.error); return }
    setRows(r.rows ?? [])
  }, [circuitJson])

  useEffect(() => { loadTable() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const onCellEdit = (rowName, kind, col, val) => {
    setPending(prev => ({
      ...prev,
      [rowName]: { ...(prev[rowName] ?? {}), [col]: val },
    }))
    setCommitResult(null)
  }

  const hasPending = Object.keys(pending).some(k => Object.keys(pending[k] ?? {}).length > 0)

  const commitEdits = useCallback(async () => {
    const edits = []
    for (const [rowName, cols] of Object.entries(pending)) {
      for (const [col, value] of Object.entries(cols)) {
        const row = rows.find(r => r.name === rowName)
        const kind = row?.kind ?? 'net_class'
        edits.push({ row_name: rowName, col, value, kind })
      }
    }
    if (edits.length === 0) return

    setLoading(true)
    const r = await apiPost('constraint_table_set', { circuit_json: circuitJson, edits })
    setLoading(false)

    if (r.error) { setCommitResult({ error: r.error }); return }

    setCommitResult({
      applied:  r.applied?.length  ?? 0,
      rejected: r.rejected?.length ?? 0,
      rejectedDetails: r.rejected  ?? [],
    })
    setPending({})
    if (r.circuit_json) {
      setCircuitJson(r.circuit_json)
      setRows(r.table?.rows ?? rows)
    }
  }, [pending, circuitJson, rows])

  const discardEdits = () => { setPending({}); setCommitResult(null) }

  const addRow = async () => {
    const name = addName.trim()
    if (!name) return
    const col = addKind === 'net_class' ? 'trace_width_mm' : 'trace_width_mm'
    const r = await apiPost('constraint_table_set', {
      circuit_json: circuitJson,
      edits: [{ row_name: name, col, value: 0.25, kind: addKind }],
    })
    if (r.circuit_json) {
      setCircuitJson(r.circuit_json)
      setRows(r.table?.rows ?? rows)
    }
    setAddName('')
  }

  const classCount = rows.filter(r => r.kind === 'net_class').length
  const netCount   = rows.filter(r => r.kind === 'net').length

  return (
    <div className="flex flex-col h-full bg-gray-950 text-gray-200 text-[12px]">
      {/* Header */}
      <div className="flex items-center gap-2 px-3 py-2 border-b border-white/10 shrink-0">
        <Table2 size={14} className="text-blue-400" />
        <span className="font-medium text-gray-100">Constraint Manager</span>
        <span className="text-[10px] text-gray-500 ml-1">
          {classCount} classes · {netCount} net overrides
        </span>
        <div className="ml-auto flex items-center gap-1.5">
          {hasPending && (
            <>
              <button onClick={discardEdits}
                      className="px-2 py-0.5 text-[10px] rounded border border-gray-600 text-gray-400 hover:text-gray-200">
                Discard
              </button>
              <button onClick={commitEdits} disabled={loading}
                      className="flex items-center gap-1 px-2.5 py-0.5 bg-blue-700/40 hover:bg-blue-700/60
                                 border border-blue-500/50 rounded text-blue-300 text-[10px] transition-colors">
                <Save size={10} /> Apply
              </button>
            </>
          )}
          <button onClick={() => loadTable()}
                  className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-gray-300"
                  title="Refresh">
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} />
          </button>
          {onClose && (
            <button onClick={onClose}
                    className="p-1 rounded hover:bg-white/10 text-gray-500 hover:text-gray-300">
              <X size={13} />
            </button>
          )}
        </div>
      </div>

      {/* Status bar */}
      {error && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-red-900/20 border-b border-red-800/40 text-red-400 text-[11px] shrink-0">
          <AlertTriangle size={11} /> {error}
        </div>
      )}
      {commitResult && !commitResult.error && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-green-900/10 border-b border-green-800/30 text-[11px] shrink-0">
          <CheckCircle2 size={11} className="text-green-400" />
          <span className="text-green-300">{commitResult.applied} edit{commitResult.applied !== 1 ? 's' : ''} applied</span>
          {commitResult.rejected > 0 && (
            <span className="text-yellow-400 ml-2">
              {commitResult.rejected} rejected: {commitResult.rejectedDetails.map(r => r.reason).join('; ')}
            </span>
          )}
        </div>
      )}
      {commitResult?.error && (
        <div className="flex items-center gap-2 px-3 py-1.5 bg-red-900/20 border-b border-red-800/40 text-red-400 text-[11px] shrink-0">
          <AlertTriangle size={11} /> {commitResult.error}
        </div>
      )}
      {hasPending && !commitResult && (
        <div className="px-3 py-1 bg-blue-900/10 border-b border-blue-800/20 text-blue-400 text-[10px] shrink-0">
          Unsaved changes — click Apply or press Discard
        </div>
      )}

      {/* Spreadsheet */}
      <div className="flex-1 overflow-auto">
        {loading && rows.length === 0 ? (
          <div className="flex items-center justify-center h-24 text-gray-600 text-[11px]">
            <RefreshCw size={13} className="animate-spin mr-2" /> Loading…
          </div>
        ) : (
          <table className="w-full border-collapse text-[11px]" style={{ tableLayout: 'fixed', minWidth: 800 }}>
            <thead className="sticky top-0 z-10 bg-gray-950">
              <tr className="border-b border-white/10">
                {DISPLAY_COLUMNS.map(col => (
                  <th key={col.key}
                      className="px-2 py-1.5 text-left text-[10px] text-gray-500 font-medium select-none"
                      style={{ width: col.width, minWidth: col.width }}>
                    {col.label}
                    {!col.readonly && (
                      <span className="ml-1 text-gray-700" title="Editable">✎</span>
                    )}
                  </th>
                ))}
              </tr>
              {/* Column-width rule line */}
              <tr className="border-b-2 border-blue-900/40 h-0">
                {DISPLAY_COLUMNS.map(col => (
                  <th key={col.key} className="p-0" style={{ width: col.width, minWidth: col.width }} />
                ))}
              </tr>
            </thead>
            <tbody>
              {/* Net-class rows */}
              {rows.filter(r => r.kind === 'net_class').map(row => (
                <Row
                  key={row.name}
                  row={row}
                  pending={pending[row.name]}
                  onCellEdit={onCellEdit}
                />
              ))}
              {/* Separator */}
              {netCount > 0 && (
                <tr>
                  <td colSpan={DISPLAY_COLUMNS.length}
                      className="py-0.5 px-2 text-[9px] text-gray-600 bg-white/[0.015] border-y border-white/5">
                    Per-net overrides
                  </td>
                </tr>
              )}
              {/* Net override rows */}
              {rows.filter(r => r.kind === 'net').map(row => (
                <Row
                  key={row.name}
                  row={row}
                  pending={pending[row.name]}
                  onCellEdit={onCellEdit}
                />
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Add row footer */}
      <div className="flex items-center gap-2 px-3 py-2 border-t border-white/10 bg-gray-950 shrink-0">
        <Plus size={11} className="text-gray-600" />
        <input
          value={addName}
          onChange={e => setAddName(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && addRow()}
          placeholder="net-class or net name…"
          className="flex-1 bg-white/5 border border-white/10 rounded px-2 py-1
                     text-[11px] font-mono text-gray-300 placeholder-gray-600
                     focus:outline-none focus:border-blue-600"
        />
        <select
          value={addKind}
          onChange={e => setAddKind(e.target.value)}
          className="bg-gray-800 border border-white/10 rounded px-2 py-1
                     text-[11px] text-gray-300 focus:outline-none focus:border-blue-600">
          <option value="net_class">Class</option>
          <option value="net">Net override</option>
        </select>
        <button
          onClick={addRow}
          disabled={!addName.trim() || loading}
          className="px-2.5 py-1 bg-blue-800/40 hover:bg-blue-800/60
                     border border-blue-600/40 rounded text-blue-300 text-[11px] transition-colors disabled:opacity-40">
          Add
        </button>
        <span className="text-[10px] text-gray-600 ml-1">Click any cell to edit</span>
      </div>
    </div>
  )
}
