/**
 * XRefManagerPanel.jsx — Federated BIM external references (XRef / hotlinked modules).
 *
 * Links external BIM model files into a host model as positioned, read-only
 * overlays for coordination, with reload and nested-reference resolution.
 *
 * Props (from the panel registry via Editor.jsx):
 *   { file, content, projectId, fileId, callTool }
 *   `content` is JSON: { links:[{id,name,path,origin_xyz_mm,rotation_deg,nested,status}] }
 *   `callTool(name, args)` dispatches a registered tool.
 */

import { useCallback, useMemo, useState } from 'react'
import { Link2, RefreshCw, FileSymlink, AlertTriangle, CheckCircle2 } from 'lucide-react'

function parseContent(content) {
  if (!content) return {}
  try {
    return typeof content === 'string' ? JSON.parse(content) : content
  } catch {
    return {}
  }
}

export default function XRefManagerPanel({ content, projectId, fileId, callTool }) {
  const initial = useMemo(() => parseContent(content), [content])
  const [state, setState] = useState(initial)
  const [busy, setBusy] = useState(null)
  const [error, setError] = useState(null)

  const links = state.links || state.xrefs || []

  const run = useCallback(async (tool, args, key) => {
    if (!callTool) return
    setBusy(key)
    setError(null)
    try {
      const res = await callTool(tool, { project_id: projectId, file_id: fileId, ...args })
      const next = res?.result ?? res
      if (next && typeof next === 'object') setState((s) => ({ ...s, ...next }))
    } catch (e) {
      setError(String(e?.message || e))
    } finally {
      setBusy(null)
    }
  }, [callTool, projectId, fileId])

  return (
    <div className="flex flex-col h-full min-h-0 overflow-auto text-sm" style={{ padding: '14px' }}>
      <div className="flex items-center gap-2" style={{ marginBottom: '6px' }}>
        <Link2 size={16} className="text-violet-500" />
        <h3 className="font-semibold" style={{ fontSize: '14px' }}>Federated XRef / Hotlinked Modules</h3>
      </div>
      <div style={{ fontSize: '11px', color: '#94a3b8', marginBottom: '12px' }}>
        External models linked as read-only overlays · reload + nested resolution
      </div>

      <button
        onClick={() => run('bim_xref_reload', {}, 'reload')}
        disabled={!!busy}
        style={{ ...btn, marginBottom: '12px' }}
      >
        <RefreshCw size={13} className={busy === 'reload' ? 'animate-spin' : ''} /> Reload all references
      </button>

      {error && (
        <div style={{ ...card, borderColor: '#fca5a5', color: '#b91c1c', marginBottom: '10px' }}>{error}</div>
      )}

      {links.length === 0 ? (
        <div style={{ fontSize: '12px', color: '#94a3b8' }}>No external references linked.</div>
      ) : (
        links.map((x) => {
          const id = x.id || x.name
          const stale = x.status === 'stale' || x.out_of_date
          return (
            <div key={id} style={card}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FileSymlink size={13} className="text-slate-500" />
                <span style={{ fontWeight: 600 }}>{x.name || id}</span>
                {stale ? (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', fontSize: '11px', color: '#b45309' }}>
                    <AlertTriangle size={11} /> stale
                  </span>
                ) : (
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', fontSize: '11px', color: '#16a34a' }}>
                    <CheckCircle2 size={11} /> current
                  </span>
                )}
              </div>
              <div style={{ fontSize: '11px', color: '#64748b', marginTop: '3px' }}>
                {x.path || '—'}
              </div>
              <div style={{ fontSize: '11px', color: '#94a3b8', marginTop: '2px' }}>
                origin {fmtXYZ(x.origin_xyz_mm)} · rot {x.rotation_deg ?? 0}°
                {x.nested ? ` · ${(x.nested.length ?? x.nested)} nested` : ''}
                {' · read-only'}
              </div>
              <button
                onClick={() => run('bim_xref_reload', { xref_id: id }, `rl-${id}`)}
                disabled={!!busy}
                style={{ ...btn, marginTop: '6px' }}
              >
                <RefreshCw size={12} /> Reload
              </button>
            </div>
          )
        })
      )}
    </div>
  )
}

function fmtXYZ(v) {
  if (!Array.isArray(v)) return '(0, 0, 0)'
  return `(${v.map((n) => Number(n).toFixed(0)).join(', ')})`
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
