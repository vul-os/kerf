/**
 * WorksharingPanel.jsx — BIM element worksharing (central-model checkout/borrow/sync).
 *
 * Mirrors the Revit/Tekla worksharing model: a central model + per-element
 * borrowing (exclusive checkout), workset ownership, and synchronize-to-central
 * with conflict detection. This is NOT live CRDT co-editing.
 *
 * Props (from the panel registry via Editor.jsx):
 *   { file, content, projectId, fileId, callTool }
 *   `content` is JSON: { worksets:[], borrows:[], conflicts:[], elements:[] }
 *   `callTool(name, args)` dispatches a registered LLM/JSON-RPC tool.
 */

import { useCallback, useMemo, useState } from 'react'
import {
  Lock, Unlock, RefreshCw, Users, AlertTriangle, CheckCircle2, Layers,
} from 'lucide-react'

function parseContent(content) {
  if (!content) return {}
  try {
    return typeof content === 'string' ? JSON.parse(content) : content
  } catch {
    return {}
  }
}

export default function WorksharingPanel({ content, projectId, fileId, callTool }) {
  const initial = useMemo(() => parseContent(content), [content])
  const [state, setState] = useState(initial)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  const dispatch = callTool

  const worksets = state.worksets || []
  const borrows = state.borrows || []
  const conflicts = state.conflicts || []
  const elements = state.elements || []

  const run = useCallback(async (tool, args, key) => {
    if (!dispatch) return
    setBusy(key)
    setError(null)
    try {
      const res = await dispatch(tool, { project_id: projectId, file_id: fileId, ...args })
      const next = res?.result ?? res
      if (next && typeof next === 'object') setState((s) => ({ ...s, ...next }))
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setBusy(null)
    }
  }, [dispatch, projectId, fileId])

  const borrowedIds = new Set(borrows.map((b) => b.element_id))

  return (
    <div className="flex flex-col h-full min-h-0 overflow-auto text-sm" style={{ padding: '14px' }}>
      <div className="flex items-center gap-2" style={{ marginBottom: '6px' }}>
        <Users size={16} className="text-blue-500" />
        <h3 className="font-semibold" style={{ fontSize: '14px' }}>BIM Worksharing</h3>
        <span style={{ fontSize: '11px', color: '#94a3b8' }}>
          central-model checkout / borrow / sync · not live co-editing
        </span>
      </div>

      <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
        <button
          onClick={() => run('bim_worksharing_status', {}, 'status')}
          disabled={!!busy}
          style={btn}
        >
          <RefreshCw size={13} /> Refresh status
        </button>
        <button
          onClick={() => run('bim_worksharing_sync', {}, 'sync')}
          disabled={!!busy}
          style={{ ...btn, background: '#1d4ed8', color: '#fff', borderColor: '#1d4ed8' }}
        >
          <RefreshCw size={13} className={busy === 'sync' ? 'animate-spin' : ''} /> Synchronize to central
        </button>
      </div>

      {error && (
        <div style={{ ...card, borderColor: '#fca5a5', color: '#b91c1c', marginBottom: '10px' }}>
          {error}
        </div>
      )}

      {/* Conflicts */}
      {conflicts.length > 0 && (
        <div style={{ ...card, borderColor: '#fca5a5', marginBottom: '12px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#b91c1c', fontWeight: 600 }}>
            <AlertTriangle size={14} /> {conflicts.length} sync conflict(s)
          </div>
          <ul style={{ margin: '6px 0 0', paddingLeft: '18px', color: '#7f1d1d' }}>
            {conflicts.map((c, i) => (
              <li key={i}>{c.element_id}: edited by {c.other_user || 'another user'}</li>
            ))}
          </ul>
        </div>
      )}

      {/* Worksets */}
      <SectionHeader icon={<Layers size={13} />} title={`Worksets (${worksets.length})`} />
      {worksets.length === 0 ? (
        <Empty>No worksets defined.</Empty>
      ) : (
        worksets.map((w) => (
          <div key={w.id || w.name} style={card}>
            <div style={{ fontWeight: 600 }}>{w.name}</div>
            <div style={{ fontSize: '11px', color: '#64748b' }}>
              owner: {w.owner || '—'} · {(w.element_ids || []).length} elements
            </div>
          </div>
        ))
      )}

      {/* Elements + borrow controls */}
      <SectionHeader icon={<Lock size={13} />} title={`Elements (${elements.length})`} />
      {elements.length === 0 ? (
        <Empty>No elements in central model. Borrows: {borrows.length}.</Empty>
      ) : (
        elements.map((el) => {
          const id = el.id || el.element_id
          const borrowed = borrowedIds.has(id)
          return (
            <div key={id} style={{ ...card, display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span style={{ fontWeight: 600 }}>{el.name || id}</span>
                <span style={{ fontSize: '11px', color: borrowed ? '#b45309' : '#16a34a', marginLeft: '8px' }}>
                  {borrowed ? 'borrowed' : 'available'}
                </span>
              </div>
              {borrowed ? (
                <button onClick={() => run('bim_worksharing_release', { element_id: id }, `rel-${id}`)} disabled={!!busy} style={btn}>
                  <Unlock size={12} /> Release
                </button>
              ) : (
                <button onClick={() => run('bim_worksharing_borrow', { element_id: id }, `bor-${id}`)} disabled={!!busy} style={btn}>
                  <Lock size={12} /> Borrow
                </button>
              )}
            </div>
          )
        })
      )}

      {conflicts.length === 0 && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: '#16a34a', fontSize: '12px', marginTop: '12px' }}>
          <CheckCircle2 size={14} /> In sync with central — no conflicts.
        </div>
      )}
    </div>
  )
}

const btn = {
  display: 'inline-flex', alignItems: 'center', gap: '5px',
  fontSize: '12px', padding: '5px 9px', borderRadius: '6px',
  border: '1px solid #cbd5e1', background: '#f8fafc', cursor: 'pointer',
}
const card = {
  background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: '6px',
  padding: '8px 10px', marginBottom: '6px',
}

function SectionHeader({ icon, title }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', margin: '12px 0 6px', fontWeight: 600, fontSize: '12px', color: '#475569' }}>
      {icon} {title}
    </div>
  )
}
function Empty({ children }) {
  return <div style={{ fontSize: '12px', color: '#94a3b8', padding: '6px 0' }}>{children}</div>
}
