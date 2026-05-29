/**
 * WorkersTab — GPU Worker enrollment and management panel.
 *
 * Renders inside the Settings page.  Lists enrolled GPU workers, shows
 * status + last-seen, and lets the user enroll a new worker (one-time
 * token reveal + CLI hint) or revoke an existing one.
 */
import { useEffect, useState } from 'react'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Copy,
  CpuIcon,
  Loader2,
  Plus,
  RefreshCw,
  Terminal,
  Trash2,
  Wifi,
  WifiOff,
  X,
} from 'lucide-react'
import Card from './Card.jsx'
import Button from './Button.jsx'
import Input from './Input.jsx'
import { api, ApiError } from '../lib/api.js'

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------

async function apiListWorkers() {
  return api.listWorkers ? api.listWorkers() : fetch('/api/workers', {
    headers: { Authorization: `Bearer ${_getToken()}` },
  }).then(r => r.json())
}

async function apiEnrollWorker(name, capabilities) {
  return fetch('/api/workers/enroll', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${_getToken()}`,
    },
    body: JSON.stringify({ name, capabilities }),
  }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e?.detail || 'Enroll failed'))))
}

async function apiDeleteWorker(id) {
  return fetch(`/api/workers/${id}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${_getToken()}` },
  }).then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e?.detail || 'Delete failed'))))
}

function _getToken() {
  try {
    const { accessToken } = window.__kerf_auth_state__ || JSON.parse(localStorage.getItem('kerf_auth') || '{}')
    return accessToken || ''
  } catch { return '' }
}

// ---------------------------------------------------------------------------
// Status badge
// ---------------------------------------------------------------------------

function StatusBadge({ status }) {
  const map = {
    online:  { icon: <Wifi size={11} />, label: 'Online',  cls: 'text-emerald-400 bg-emerald-400/10 border-emerald-400/20' },
    busy:    { icon: <CpuIcon size={11} />, label: 'Busy', cls: 'text-amber-400 bg-amber-400/10 border-amber-400/20' },
    offline: { icon: <WifiOff size={11} />, label: 'Offline', cls: 'text-ink-400 bg-ink-400/10 border-ink-700' },
  }
  const { icon, label, cls } = map[status] || map.offline
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full border text-[10px] font-medium ${cls}`}>
      {icon}{label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Worker row
// ---------------------------------------------------------------------------

function WorkerRow({ worker, onRevoke }) {
  const [revoking, setRevoking] = useState(false)

  const onDelete = async () => {
    if (!window.confirm(`Revoke worker "${worker.name}"? The machine will no longer be able to authenticate.`)) return
    setRevoking(true)
    try {
      await apiDeleteWorker(worker.id)
      onRevoke(worker.id)
    } catch (e) {
      alert(e?.message || 'Revoke failed')
    } finally {
      setRevoking(false)
    }
  }

  const caps = worker.capabilities || {}
  const capSummary = [
    caps.gpu_type,
    caps.vram_gb ? `${caps.vram_gb} GB VRAM` : null,
    caps.supported_workloads?.length ? caps.supported_workloads.join(', ') : null,
  ].filter(Boolean).join(' · ') || 'No capabilities reported'

  const lastSeen = worker.last_seen_at
    ? new Date(worker.last_seen_at).toLocaleString()
    : 'Never'

  return (
    <div className="flex items-start justify-between gap-4 py-3 border-b border-ink-800 last:border-0">
      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2 mb-1">
          <span className="font-medium text-sm text-ink-100 truncate">{worker.name}</span>
          <StatusBadge status={worker.status} />
        </div>
        <p className="text-[11px] text-ink-500 truncate">{capSummary}</p>
        <p className="text-[11px] text-ink-600 mt-0.5 flex items-center gap-1">
          <Clock size={10} />
          Last seen: {lastSeen}
        </p>
      </div>
      <Button
        type="button"
        variant="ghost"
        size="sm"
        onClick={onDelete}
        disabled={revoking}
        aria-label={`Revoke ${worker.name}`}
      >
        {revoking ? <Loader2 size={12} className="animate-spin" /> : <Trash2 size={12} />}
        Revoke
      </Button>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Enroll modal
// ---------------------------------------------------------------------------

function EnrollModal({ onClose, onEnrolled }) {
  const [name, setName] = useState('')
  const [gpuType, setGpuType] = useState('')
  const [vramGb, setVramGb] = useState('')
  const [enrolling, setEnrolling] = useState(false)
  const [result, setResult] = useState(null)
  const [err, setErr] = useState(null)
  const [copied, setCopied] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    if (!name.trim()) { setErr('Name is required'); return }
    setEnrolling(true); setErr(null)
    try {
      const caps = {}
      if (gpuType.trim()) caps.gpu_type = gpuType.trim()
      if (vramGb.trim()) caps.vram_gb = parseInt(vramGb, 10) || undefined
      caps.supported_workloads = ['render']
      const data = await apiEnrollWorker(name.trim(), caps)
      setResult(data)
      onEnrolled?.(data)
    } catch (e) {
      setErr(e?.message || 'Enrollment failed')
    } finally {
      setEnrolling(false)
    }
  }

  const copyToken = () => {
    if (!result?.token) return
    navigator.clipboard.writeText(result.token).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    })
  }

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Enroll GPU worker"
      className="fixed inset-0 z-50 flex items-center justify-center bg-ink-950/80 backdrop-blur-sm p-4"
    >
      <div className="bg-ink-900 border border-ink-800 rounded-2xl shadow-2xl w-full max-w-md p-6">
        <div className="flex items-center justify-between mb-5">
          <div className="flex items-center gap-2">
            <CpuIcon size={18} className="text-kerf-300" />
            <h2 className="font-display text-lg font-semibold">Enroll GPU Worker</h2>
          </div>
          <button
            type="button"
            aria-label="Close"
            className="p-1 rounded-lg text-ink-400 hover:text-ink-100 hover:bg-ink-800"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {result ? (
          /* Token reveal — shown ONCE */
          <div className="space-y-4">
            <div className="flex items-center gap-2 text-emerald-400 text-sm">
              <CheckCircle2 size={16} />
              Worker <strong>{result.name}</strong> enrolled.
            </div>
            <div>
              <p className="text-[11px] font-medium text-ink-300 uppercase tracking-wider mb-1.5">
                One-time token — copy now, it cannot be retrieved
              </p>
              <div className="relative">
                <div className="font-mono text-[11px] bg-ink-950 border border-ink-700 rounded-lg px-3 py-2 pr-10 break-all text-kerf-300 select-all">
                  {result.token}
                </div>
                <button
                  type="button"
                  aria-label="Copy token"
                  className="absolute right-2 top-2 text-ink-400 hover:text-ink-100"
                  onClick={copyToken}
                >
                  {copied ? <CheckCircle2 size={14} className="text-emerald-400" /> : <Copy size={14} />}
                </button>
              </div>
            </div>
            <div>
              <p className="text-[11px] font-medium text-ink-300 uppercase tracking-wider mb-1.5 flex items-center gap-1">
                <Terminal size={11} />
                Install on your worker machine
              </p>
              <pre className="font-mono text-[11px] bg-ink-950 border border-ink-700 rounded-lg px-3 py-2 text-ink-300 overflow-x-auto whitespace-pre-wrap break-all">
                {result.cli_hint || `pip install kerf-worker && kerf-worker enroll ${result.token}`}
              </pre>
            </div>
            <Button type="button" variant="primary" size="md" className="w-full" onClick={onClose}>
              Done
            </Button>
          </div>
        ) : (
          /* Enrollment form */
          <form className="space-y-4" onSubmit={onSubmit}>
            {err && (
              <div
                role="alert"
                className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200"
              >
                <AlertCircle size={14} className="mt-0.5 shrink-0" />
                <span>{err}</span>
              </div>
            )}
            <Input
              label="Worker name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="my-rtx-4090-rig"
              required
              autoFocus
            />
            <Input
              label="GPU type (optional)"
              value={gpuType}
              onChange={(e) => setGpuType(e.target.value)}
              placeholder="RTX 4090"
            />
            <Input
              label="VRAM GB (optional)"
              type="number"
              min="1"
              value={vramGb}
              onChange={(e) => setVramGb(e.target.value)}
              placeholder="24"
            />
            <p className="text-[11px] text-ink-500 leading-relaxed">
              Enrolling a worker links your GPU machine to your account.
              Jobs assigned to this worker are billed to your own hardware —
              no Kerf credits are consumed.
            </p>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="ghost" size="md" onClick={onClose} disabled={enrolling}>
                Cancel
              </Button>
              <Button type="submit" variant="primary" size="md" disabled={enrolling || !name.trim()}>
                {enrolling ? <Loader2 size={13} className="animate-spin" /> : <Plus size={13} />}
                {enrolling ? 'Enrolling…' : 'Enroll worker'}
              </Button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// WorkersTab (main export)
// ---------------------------------------------------------------------------

export default function WorkersTab() {
  const [workers, setWorkers] = useState([])
  const [loading, setLoading] = useState(true)
  const [err, setErr] = useState(null)
  const [showEnroll, setShowEnroll] = useState(false)

  const load = async () => {
    setLoading(true); setErr(null)
    try {
      const data = await apiListWorkers()
      setWorkers(Array.isArray(data) ? data : [])
    } catch (e) {
      setErr(e?.message || 'Could not load workers')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { load() }, [])

  const onRevoke = (id) => setWorkers(ws => ws.filter(w => w.id !== id))
  const onEnrolled = (data) => {
    setWorkers(ws => [{ id: data.id, name: data.name, status: 'offline', capabilities: {}, last_seen_at: null }, ...ws])
    setShowEnroll(false)
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="font-display text-base font-semibold">GPU Workers</h2>
          <p className="text-[12px] text-ink-400 mt-0.5">
            Enroll your own GPU machines. Jobs run on your hardware — no Kerf credits charged.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            aria-label="Refresh"
            onClick={load}
            disabled={loading}
          >
            {loading ? <Loader2 size={13} className="animate-spin" /> : <RefreshCw size={13} />}
          </Button>
          <Button
            type="button"
            variant="primary"
            size="sm"
            onClick={() => setShowEnroll(true)}
          >
            <Plus size={13} />
            Enroll worker
          </Button>
        </div>
      </div>

      <Card className="px-4 py-2">
        {loading ? (
          <div className="py-8 flex justify-center text-ink-500">
            <Loader2 size={20} className="animate-spin" />
          </div>
        ) : err ? (
          <div
            role="alert"
            className="flex items-center gap-2 py-4 text-sm text-red-300"
          >
            <AlertCircle size={14} />
            {err}
          </div>
        ) : workers.length === 0 ? (
          <div className="py-8 flex flex-col items-center gap-2 text-ink-500">
            <CpuIcon size={28} className="opacity-30" />
            <p className="text-sm">No workers enrolled yet.</p>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => setShowEnroll(true)}
            >
              <Plus size={12} />
              Enroll your first worker
            </Button>
          </div>
        ) : (
          workers.map(w => (
            <WorkerRow key={w.id} worker={w} onRevoke={onRevoke} />
          ))
        )}
      </Card>

      {showEnroll && (
        <EnrollModal
          onClose={() => setShowEnroll(false)}
          onEnrolled={onEnrolled}
        />
      )}
    </div>
  )
}
