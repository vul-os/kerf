/**
 * BCFIssueManager — buildingSMART BCF 3.0 clash/issue workflow panel.
 *
 * Features
 * --------
 * - Filter bar:  status · priority · assignee · discipline
 * - Topic table: title, status badge, priority badge, assignee, due date
 * - Detail panel (selected topic): description, threaded comments, viewpoint
 *   thumbnail placeholder, status dropdown
 * - Add Topic modal (form)
 * - Export BCF button → downloads .bcf zip via API
 * - Import BCF button → file picker, merges into project
 *
 * Props
 * -----
 * projectId  {string}   Kerf project UUID (for API calls)
 * className  {string}   Extra Tailwind classes on root element
 *
 * Routing
 * -------
 * Mounted at /issues (lazy-loaded from App.jsx).
 */

import { useState, useMemo, useRef, useCallback } from 'react'
import {
  Plus,
  Upload,
  Download,
  ChevronDown,
  MessageSquare,
  Eye,
  Filter,
  X,
  AlertTriangle,
  CheckCircle2,
  Clock,
  Circle,
} from 'lucide-react'

// ── Constants ─────────────────────────────────────────────────────────────────

const TOPIC_TYPES  = ['Clash', 'Issue', 'Request', 'Fault', 'Inquiry']
const PRIORITIES   = ['Critical', 'Normal', 'Minor']
const STATUSES     = ['Open', 'In Progress', 'Resolved', 'Closed']
const DISCIPLINES  = ['Architecture', 'Structure', 'MEP', 'Civil', 'Coordination', 'Other']

// ── Badges ────────────────────────────────────────────────────────────────────

const STATUS_STYLES = {
  'Open':        'bg-blue-500/20 text-blue-300 border-blue-500/40',
  'In Progress': 'bg-amber-500/20 text-amber-300 border-amber-500/40',
  'Resolved':    'bg-emerald-500/20 text-emerald-300 border-emerald-500/40',
  'Closed':      'bg-ink-600/40 text-ink-400 border-ink-600/60',
}

const PRIORITY_STYLES = {
  'Critical': 'bg-red-500/20 text-red-300 border-red-500/40',
  'Normal':   'bg-sky-500/20 text-sky-300 border-sky-500/40',
  'Minor':    'bg-ink-600/30 text-ink-400 border-ink-600/50',
}

const STATUS_ICON = {
  'Open':        <Circle        size={11} className="inline -mt-0.5 mr-0.5" />,
  'In Progress': <Clock         size={11} className="inline -mt-0.5 mr-0.5" />,
  'Resolved':    <CheckCircle2  size={11} className="inline -mt-0.5 mr-0.5" />,
  'Closed':      <CheckCircle2  size={11} className="inline -mt-0.5 mr-0.5 opacity-40" />,
}

function StatusBadge({ status }) {
  const cls = STATUS_STYLES[status] ?? 'bg-ink-700 text-ink-300 border-ink-600'
  return (
    <span className={`inline-flex items-center gap-0.5 rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {STATUS_ICON[status]}
      {status}
    </span>
  )
}

function PriorityBadge({ priority }) {
  const cls = PRIORITY_STYLES[priority] ?? 'bg-ink-700 text-ink-300 border-ink-600'
  return (
    <span className={`inline-flex items-center rounded-full border px-2 py-0.5 text-[11px] font-medium ${cls}`}>
      {priority === 'Critical' && <AlertTriangle size={10} className="mr-0.5 inline" />}
      {priority}
    </span>
  )
}

// ── Filter bar ────────────────────────────────────────────────────────────────

function FilterSelect({ label, value, options, onChange }) {
  return (
    <div className="flex items-center gap-1.5">
      <span className="text-[11px] text-ink-400 whitespace-nowrap">{label}</span>
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="rounded border border-ink-700 bg-ink-800 px-2 py-1 text-xs text-ink-200 focus:border-kerf-500 focus:outline-none"
      >
        <option value="">All</option>
        {options.map((o) => (
          <option key={o} value={o}>{o}</option>
        ))}
      </select>
    </div>
  )
}

// ── Add Topic modal ───────────────────────────────────────────────────────────

function AddTopicModal({ onAdd, onClose }) {
  const [form, setForm] = useState({
    title:       '',
    description: '',
    topic_type:  'Issue',
    priority:    'Normal',
    status:      'Open',
    assigned_to: '',
    due_date:    '',
    discipline:  'Architecture',
  })

  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  const isValid = form.title.trim().length > 0

  const handleSubmit = (e) => {
    e.preventDefault()
    if (!isValid) return
    onAdd({
      ...form,
      guid:               crypto.randomUUID?.() ?? Math.random().toString(36).slice(2),
      creation_date_iso:  new Date().toISOString(),
      creation_author:    '',
      modified_date_iso:  new Date().toISOString(),
      due_date_iso:        form.due_date,
      comments:           [],
      viewpoints:         [],
    })
    onClose()
  }

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={(e) => e.target === e.currentTarget && onClose()}
    >
      <div className="w-full max-w-lg rounded-xl border border-ink-700 bg-ink-900 p-6 shadow-2xl">
        <div className="mb-4 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-ink-100">New BCF Topic</h2>
          <button type="button" onClick={onClose} className="rounded p-1 text-ink-400 hover:bg-ink-800 hover:text-ink-200">
            <X size={15} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div>
            <label className="mb-1 block text-xs text-ink-400">Title *</label>
            <input
              type="text"
              required
              value={form.title}
              onChange={set('title')}
              placeholder="e.g. Duct clash at level 3 / grid A2"
              className="w-full rounded border border-ink-700 bg-ink-800 px-3 py-2 text-sm text-ink-100 placeholder-ink-600 focus:border-kerf-500 focus:outline-none"
            />
          </div>
          <div>
            <label className="mb-1 block text-xs text-ink-400">Description</label>
            <textarea
              rows={3}
              value={form.description}
              onChange={set('description')}
              placeholder="Describe the issue…"
              className="w-full resize-none rounded border border-ink-700 bg-ink-800 px-3 py-2 text-sm text-ink-100 placeholder-ink-600 focus:border-kerf-500 focus:outline-none"
            />
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="mb-1 block text-xs text-ink-400">Type</label>
              <select value={form.topic_type} onChange={set('topic_type')}
                className="w-full rounded border border-ink-700 bg-ink-800 px-2 py-2 text-sm text-ink-200 focus:border-kerf-500 focus:outline-none">
                {TOPIC_TYPES.map((t) => <option key={t}>{t}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-ink-400">Priority</label>
              <select value={form.priority} onChange={set('priority')}
                className="w-full rounded border border-ink-700 bg-ink-800 px-2 py-2 text-sm text-ink-200 focus:border-kerf-500 focus:outline-none">
                {PRIORITIES.map((p) => <option key={p}>{p}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-ink-400">Discipline</label>
              <select value={form.discipline} onChange={set('discipline')}
                className="w-full rounded border border-ink-700 bg-ink-800 px-2 py-2 text-sm text-ink-200 focus:border-kerf-500 focus:outline-none">
                {DISCIPLINES.map((d) => <option key={d}>{d}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-xs text-ink-400">Assigned To</label>
              <input
                type="email"
                value={form.assigned_to}
                onChange={set('assigned_to')}
                placeholder="email@example.com"
                className="w-full rounded border border-ink-700 bg-ink-800 px-2 py-2 text-sm text-ink-100 placeholder-ink-600 focus:border-kerf-500 focus:outline-none"
              />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-xs text-ink-400">Due Date</label>
            <input
              type="date"
              value={form.due_date}
              onChange={set('due_date')}
              className="rounded border border-ink-700 bg-ink-800 px-2 py-2 text-sm text-ink-200 focus:border-kerf-500 focus:outline-none"
            />
          </div>
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose}
              className="rounded px-3 py-1.5 text-xs text-ink-400 hover:bg-ink-800 hover:text-ink-200">
              Cancel
            </button>
            <button type="submit" disabled={!isValid}
              className="rounded bg-kerf-600 px-4 py-1.5 text-xs font-medium text-white hover:bg-kerf-500 disabled:cursor-not-allowed disabled:opacity-50">
              Create Topic
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ── Detail panel ──────────────────────────────────────────────────────────────

function DetailPanel({ topic, comments, viewpoints, onStatusChange, onAddComment }) {
  const [commentText, setCommentText] = useState('')
  const topicComments  = comments.filter((c) => c.topic_guid === topic.guid)
  const topicViewpoints = viewpoints.filter((vp) => vp.topic_guid === topic.guid)

  const submitComment = () => {
    if (!commentText.trim()) return
    onAddComment(topic.guid, commentText)
    setCommentText('')
  }

  return (
    <div className="flex h-full flex-col overflow-hidden">
      {/* Header */}
      <div className="border-b border-ink-800 px-4 py-3">
        <div className="mb-1.5 flex items-start gap-2">
          <span className="mt-0.5 rounded bg-ink-700 px-1.5 py-0.5 text-[10px] font-mono text-ink-400">
            {topic.topic_type?.toUpperCase()}
          </span>
          <h2 className="flex-1 text-sm font-semibold text-ink-100 leading-tight">{topic.title}</h2>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={topic.status} />
          <PriorityBadge priority={topic.priority} />
          {topic.assigned_to && (
            <span className="text-[11px] text-ink-400">{topic.assigned_to}</span>
          )}
          {topic.due_date_iso && (
            <span className="text-[11px] text-ink-500">
              Due: {topic.due_date_iso.slice(0, 10)}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto space-y-4 p-4 scrollbar-thin scrollbar-track-ink-900 scrollbar-thumb-ink-700">
        {/* Description */}
        {topic.description && (
          <div>
            <p className="text-xs font-medium text-ink-400 mb-1">Description</p>
            <p className="text-sm text-ink-300 leading-relaxed">{topic.description}</p>
          </div>
        )}

        {/* Viewpoints */}
        {topicViewpoints.length > 0 && (
          <div>
            <p className="text-xs font-medium text-ink-400 mb-2 flex items-center gap-1.5">
              <Eye size={11} /> Viewpoints ({topicViewpoints.length})
            </p>
            <div className="flex flex-wrap gap-2">
              {topicViewpoints.map((vp) => (
                <div key={vp.guid}
                  className="flex h-20 w-28 items-center justify-center rounded border border-ink-700 bg-ink-800/60 text-ink-600 text-[10px]">
                  {vp.snapshot_filename || 'No snapshot'}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Status change */}
        <div>
          <p className="text-xs font-medium text-ink-400 mb-1.5">Status</p>
          <select
            value={topic.status}
            onChange={(e) => onStatusChange(topic.guid, e.target.value)}
            className="rounded border border-ink-700 bg-ink-800 px-2 py-1.5 text-sm text-ink-200 focus:border-kerf-500 focus:outline-none"
          >
            {STATUSES.map((s) => <option key={s}>{s}</option>)}
          </select>
        </div>

        {/* Comments */}
        <div>
          <p className="text-xs font-medium text-ink-400 mb-2 flex items-center gap-1.5">
            <MessageSquare size={11} /> Comments ({topicComments.length})
          </p>
          {topicComments.length === 0 ? (
            <p className="text-xs text-ink-600 italic">No comments yet.</p>
          ) : (
            <ul className="space-y-2">
              {topicComments.map((c) => (
                <li key={c.guid}
                  className="rounded-lg border border-ink-800 bg-ink-800/40 px-3 py-2">
                  <div className="flex items-center justify-between mb-0.5">
                    <span className="text-[11px] font-medium text-kerf-400">{c.author || 'Unknown'}</span>
                    <span className="text-[10px] text-ink-600">{c.date_iso?.slice(0, 10)}</span>
                  </div>
                  <p className="text-xs text-ink-300 leading-relaxed">{c.comment}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* New comment input */}
      <div className="border-t border-ink-800 p-3">
        <div className="flex gap-2">
          <input
            type="text"
            value={commentText}
            onChange={(e) => setCommentText(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && !e.shiftKey && submitComment()}
            placeholder="Add a comment… (Enter to send)"
            className="flex-1 rounded border border-ink-700 bg-ink-800 px-3 py-2 text-xs text-ink-100 placeholder-ink-600 focus:border-kerf-500 focus:outline-none"
          />
          <button
            type="button"
            onClick={submitComment}
            disabled={!commentText.trim()}
            className="rounded bg-kerf-700 px-3 py-2 text-xs text-white hover:bg-kerf-600 disabled:opacity-40"
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function BCFIssueManager({ projectId, className = '' }) {
  // ── State ──────────────────────────────────────────────────────────────────
  const [topics,     setTopics]     = useState([])
  const [comments,   setComments]   = useState([])
  const [viewpoints, setViewpoints] = useState([])
  const [selected,   setSelected]   = useState(null)  // topic guid
  const [showAdd,    setShowAdd]     = useState(false)
  const [filters,    setFilters]     = useState({ status: '', priority: '', assignee: '', discipline: '' })
  const [importError, setImportError] = useState('')

  const fileInputRef = useRef(null)

  // ── Filter logic ──────────────────────────────────────────────────────────
  const filtered = useMemo(() => {
    return topics.filter((t) => {
      if (filters.status     && t.status      !== filters.status)     return false
      if (filters.priority   && t.priority    !== filters.priority)   return false
      if (filters.assignee   && !t.assigned_to.includes(filters.assignee)) return false
      if (filters.discipline && t.discipline  !== filters.discipline) return false
      return true
    })
  }, [topics, filters])

  const setFilter = (key) => (val) => setFilters((f) => ({ ...f, [key]: val }))
  const clearFilters = () => setFilters({ status: '', priority: '', assignee: '', discipline: '' })
  const hasFilters = Object.values(filters).some(Boolean)

  // ── CRUD handlers ─────────────────────────────────────────────────────────
  const handleAddTopic = useCallback((topic) => {
    setTopics((prev) => [topic, ...prev])
  }, [])

  const handleStatusChange = useCallback((topicGuid, newStatus) => {
    setTopics((prev) =>
      prev.map((t) =>
        t.guid === topicGuid
          ? { ...t, status: newStatus, modified_date_iso: new Date().toISOString() }
          : t
      )
    )
  }, [])

  const handleAddComment = useCallback((topicGuid, text) => {
    const c = {
      guid:             crypto.randomUUID?.() ?? Math.random().toString(36).slice(2),
      topic_guid:       topicGuid,
      comment:          text,
      author:           '',
      date_iso:         new Date().toISOString(),
      modified_date_iso: new Date().toISOString(),
    }
    setComments((prev) => [...prev, c])
  }, [])

  // ── Export ────────────────────────────────────────────────────────────────
  const handleExport = useCallback(async () => {
    const project = {
      project_id: projectId || 'local',
      name:       'Kerf BCF Export',
      topics,
      comments,
      viewpoints,
    }
    try {
      const res = await fetch(`/api/projects/${projectId}/bcf/export`, {
        method:  'POST',
        headers: { 'Content-Type': 'application/json' },
        body:    JSON.stringify({ project }),
      })
      if (!res.ok) throw new Error(await res.text())
      const blob = await res.blob()
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `issues-${new Date().toISOString().slice(0, 10)}.bcf`
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      // Fallback: client-side JSON stub for offline/dev use
      const json = JSON.stringify({ project }, null, 2)
      const blob = new Blob([json], { type: 'application/json' })
      const url  = URL.createObjectURL(blob)
      const a    = document.createElement('a')
      a.href     = url
      a.download = `issues-${new Date().toISOString().slice(0, 10)}.bcf.json`
      a.click()
      URL.revokeObjectURL(url)
    }
  }, [projectId, topics, comments, viewpoints])

  // ── Import ────────────────────────────────────────────────────────────────
  const handleImport = useCallback(async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setImportError('')
    try {
      const form = new FormData()
      form.append('file', file)
      const res = await fetch(`/api/projects/${projectId}/bcf/import`, {
        method: 'POST',
        body:   form,
      })
      if (!res.ok) throw new Error(await res.text())
      const data = await res.json()
      // Merge imported topics/comments/viewpoints (deduplicate by guid)
      setTopics((prev) => {
        const existing = new Set(prev.map((t) => t.guid))
        return [...prev, ...(data.topics ?? []).filter((t) => !existing.has(t.guid))]
      })
      setComments((prev) => {
        const existing = new Set(prev.map((c) => c.guid))
        return [...prev, ...(data.comments ?? []).filter((c) => !existing.has(c.guid))]
      })
      setViewpoints((prev) => {
        const existing = new Set(prev.map((v) => v.guid))
        return [...prev, ...(data.viewpoints ?? []).filter((v) => !existing.has(v.guid))]
      })
    } catch (err) {
      setImportError(err.message || 'Import failed')
    } finally {
      e.target.value = ''
    }
  }, [projectId])

  const selectedTopic = topics.find((t) => t.guid === selected) ?? null

  // ── Render ────────────────────────────────────────────────────────────────
  return (
    <div className={`flex h-full flex-col overflow-hidden bg-ink-950 text-ink-100 ${className}`}>

      {/* ── Toolbar ── */}
      <div className="flex items-center gap-3 border-b border-ink-800 bg-ink-900 px-4 py-2.5 flex-shrink-0">
        <span className="text-sm font-semibold text-ink-100">BCF Issues</span>
        {topics.length > 0 && (
          <span className="rounded-full bg-ink-700 px-2 py-0.5 text-[11px] text-ink-300">
            {filtered.length}/{topics.length}
          </span>
        )}
        <div className="flex-1" />

        <button
          type="button"
          onClick={() => setShowAdd(true)}
          className="flex items-center gap-1.5 rounded bg-kerf-700 px-3 py-1.5 text-xs font-medium text-white hover:bg-kerf-600"
        >
          <Plus size={13} />
          Add Topic
        </button>
        <button
          type="button"
          onClick={handleExport}
          disabled={topics.length === 0}
          className="flex items-center gap-1.5 rounded border border-ink-700 bg-ink-800 px-3 py-1.5 text-xs text-ink-300 hover:bg-ink-700 hover:text-ink-100 disabled:opacity-40"
        >
          <Download size={13} />
          Export BCF
        </button>
        <button
          type="button"
          onClick={() => fileInputRef.current?.click()}
          className="flex items-center gap-1.5 rounded border border-ink-700 bg-ink-800 px-3 py-1.5 text-xs text-ink-300 hover:bg-ink-700 hover:text-ink-100"
        >
          <Upload size={13} />
          Import BCF
        </button>
        <input
          ref={fileInputRef}
          type="file"
          accept=".bcf,.bcfzip,.json"
          className="hidden"
          onChange={handleImport}
        />
      </div>

      {/* ── Filter bar ── */}
      <div className="flex flex-wrap items-center gap-3 border-b border-ink-800/60 bg-ink-900/50 px-4 py-2 flex-shrink-0">
        <Filter size={11} className="text-ink-500" />
        <FilterSelect label="Status"     value={filters.status}     options={STATUSES}    onChange={setFilter('status')} />
        <FilterSelect label="Priority"   value={filters.priority}   options={PRIORITIES}  onChange={setFilter('priority')} />
        <FilterSelect label="Discipline" value={filters.discipline} options={DISCIPLINES} onChange={setFilter('discipline')} />
        <div className="flex items-center gap-1.5">
          <span className="text-[11px] text-ink-400">Assignee</span>
          <input
            type="text"
            value={filters.assignee}
            onChange={(e) => setFilter('assignee')(e.target.value)}
            placeholder="email…"
            className="rounded border border-ink-700 bg-ink-800 px-2 py-1 text-xs text-ink-200 placeholder-ink-600 focus:border-kerf-500 focus:outline-none w-28"
          />
        </div>
        {hasFilters && (
          <button type="button" onClick={clearFilters}
            className="ml-auto flex items-center gap-1 text-[11px] text-ink-500 hover:text-ink-300">
            <X size={11} /> Clear
          </button>
        )}
      </div>

      {importError && (
        <div className="border-b border-red-800 bg-red-950/40 px-4 py-2 text-xs text-red-300 flex items-center gap-2">
          <AlertTriangle size={12} />
          {importError}
          <button type="button" onClick={() => setImportError('')} className="ml-auto">
            <X size={12} />
          </button>
        </div>
      )}

      {/* ── Main content ── */}
      <div className="flex flex-1 min-h-0 overflow-hidden">

        {/* ── Topic table ── */}
        <div className={`flex flex-col border-r border-ink-800 overflow-hidden ${selectedTopic ? 'w-[55%]' : 'flex-1'}`}>
          {filtered.length === 0 ? (
            <div className="flex flex-1 flex-col items-center justify-center gap-3 text-ink-600">
              <MessageSquare size={32} strokeWidth={1} />
              <p className="text-sm">
                {topics.length === 0
                  ? 'No topics yet — click Add Topic to get started.'
                  : 'No topics match the current filters.'}
              </p>
            </div>
          ) : (
            <div className="flex-1 overflow-y-auto scrollbar-thin scrollbar-track-ink-900 scrollbar-thumb-ink-700">
              <table className="w-full text-xs">
                <thead className="sticky top-0 z-10 bg-ink-900 border-b border-ink-800">
                  <tr>
                    <th className="px-3 py-2 text-left text-[11px] font-medium text-ink-400 w-[40%]">Title</th>
                    <th className="px-3 py-2 text-left text-[11px] font-medium text-ink-400">Status</th>
                    <th className="px-3 py-2 text-left text-[11px] font-medium text-ink-400">Priority</th>
                    <th className="px-3 py-2 text-left text-[11px] font-medium text-ink-400 hidden sm:table-cell">Assignee</th>
                    <th className="px-3 py-2 text-left text-[11px] font-medium text-ink-400 hidden md:table-cell">Due</th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((topic) => (
                    <tr
                      key={topic.guid}
                      onClick={() => setSelected(topic.guid === selected ? null : topic.guid)}
                      className={`cursor-pointer border-b border-ink-800/60 transition-colors ${
                        topic.guid === selected
                          ? 'bg-kerf-900/30 border-l-2 border-l-kerf-500'
                          : 'hover:bg-ink-800/40'
                      }`}
                    >
                      <td className="px-3 py-2.5">
                        <div className="flex flex-col gap-0.5">
                          <span className="font-medium text-ink-100 leading-snug line-clamp-1">
                            {topic.title}
                          </span>
                          {topic.topic_type && (
                            <span className="text-[10px] text-ink-500">{topic.topic_type}</span>
                          )}
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <StatusBadge status={topic.status} />
                      </td>
                      <td className="px-3 py-2.5">
                        <PriorityBadge priority={topic.priority} />
                      </td>
                      <td className="px-3 py-2.5 hidden sm:table-cell text-ink-400 truncate max-w-[120px]">
                        {topic.assigned_to || '—'}
                      </td>
                      <td className="px-3 py-2.5 hidden md:table-cell text-ink-500">
                        {topic.due_date_iso ? topic.due_date_iso.slice(0, 10) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* ── Detail panel ── */}
        {selectedTopic && (
          <div className="flex-1 min-w-0 overflow-hidden">
            <DetailPanel
              topic={selectedTopic}
              comments={comments}
              viewpoints={viewpoints}
              onStatusChange={handleStatusChange}
              onAddComment={handleAddComment}
            />
          </div>
        )}
      </div>

      {/* ── Add Topic modal ── */}
      {showAdd && (
        <AddTopicModal
          onAdd={handleAddTopic}
          onClose={() => setShowAdd(false)}
        />
      )}
    </div>
  )
}
