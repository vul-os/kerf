/**
 * ConstructionSequencingPanel.jsx — 4D Construction Sequencing (Revit parity).
 *
 * Links a task schedule (IFC4 IfcTask) to BIM elements and renders a
 * time-phased element-appearance timeline with a date-scrubber.
 *
 * Features
 * --------
 * - Task editor: add/remove tasks with start/finish dates + element IDs
 * - Date scrubber: ISO 8601 date slider to query timeline state
 * - Timeline table: element_id | task | state | progress%
 * - Summary bar: not_started / active / complete counts
 * - Critical path highlighting
 * - Validate schedule button
 *
 * Props
 * -----
 * projectId  {string}  — current project id
 * onToast    {Function} — surface errors as toasts
 */

import { useState, useCallback, useMemo } from 'react'
import {
  Calendar,
  ChevronRight,
  ChevronDown,
  ClipboardList,
  Zap,
  CheckCircle2,
  Clock,
  AlertCircle,
  Plus,
  Trash2,
} from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const IFC_TASK_TYPES = [
  'CONSTRUCTION', 'DEMOLITION', 'INSTALLATION', 'REMOVAL',
  'RENOVATION', 'MAINTENANCE', 'LOGISTIC', 'NOTDEFINED',
]

const STATE_META = {
  not_started: { label: 'Not Started', color: '#6b7280', bg: 'bg-gray-100 dark:bg-gray-800', text: 'text-gray-600 dark:text-gray-400' },
  active:      { label: 'Active',       color: '#f59e0b', bg: 'bg-amber-100 dark:bg-amber-900/30', text: 'text-amber-700 dark:text-amber-300' },
  complete:    { label: 'Complete',     color: '#22c55e', bg: 'bg-green-100 dark:bg-green-900/30', text: 'text-green-700 dark:text-green-300' },
}

const DEMO_TASKS = [
  { id: 'T1', name: 'Excavation',      start: '2025-01-06', finish: '2025-01-17', element_ids: ['found-001', 'found-002'], predecessors: [],    ifc_task_type: 'CONSTRUCTION', trade: 'civil' },
  { id: 'T2', name: 'Foundations',     start: '2025-01-20', finish: '2025-02-07', element_ids: ['slab-001'],               predecessors: ['T1'], ifc_task_type: 'CONSTRUCTION', trade: 'structural' },
  { id: 'T3', name: 'Structural Frame',start: '2025-02-10', finish: '2025-03-21', element_ids: ['col-001', 'beam-001'],    predecessors: ['T2'], ifc_task_type: 'CONSTRUCTION', trade: 'structural' },
  { id: 'T4', name: 'Exterior Walls',  start: '2025-03-24', finish: '2025-04-25', element_ids: ['wall-001', 'wall-002'],   predecessors: ['T3'], ifc_task_type: 'CONSTRUCTION', trade: 'architectural' },
  { id: 'T5', name: 'MEP Rough-in',    start: '2025-03-24', finish: '2025-05-09', element_ids: ['mep-001', 'mep-002'],    predecessors: ['T3'], ifc_task_type: 'INSTALLATION', trade: 'mep' },
]

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function today() {
  return new Date().toISOString().slice(0, 10)
}

function StatBadge({ label, count, color }) {
  return (
    <div className={`flex flex-col items-center rounded-lg px-3 py-2 ${color}`}>
      <span className="text-lg font-bold leading-tight">{count}</span>
      <span className="text-xs font-medium opacity-80">{label}</span>
    </div>
  )
}

function ProgressBar({ pct, state }) {
  const color = state === 'complete' ? '#22c55e' : state === 'active' ? '#f59e0b' : '#d1d5db'
  return (
    <div className="h-1.5 w-20 rounded-full bg-gray-200 dark:bg-gray-700 overflow-hidden">
      <div className="h-full rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  )
}

function StateBadge({ state }) {
  const m = STATE_META[state] || STATE_META.not_started
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${m.bg} ${m.text}`}>
      {m.label}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Task editor
// ---------------------------------------------------------------------------

let _nextTaskId = 10

function TaskEditor({ tasks, onChange }) {
  const addTask = useCallback(() => {
    const id = `T${++_nextTaskId}`
    onChange([...tasks, { id, name: 'New Task', start: today(), finish: today(), element_ids: [], predecessors: [], ifc_task_type: 'CONSTRUCTION', trade: '' }])
  }, [tasks, onChange])

  const removeTask = useCallback((idx) => {
    onChange(tasks.filter((_, i) => i !== idx))
  }, [tasks, onChange])

  const updateTask = useCallback((idx, field, value) => {
    const updated = tasks.map((t, i) => i === idx ? { ...t, [field]: value } : t)
    onChange(updated)
  }, [tasks, onChange])

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-ink-600 dark:text-ink-300 uppercase tracking-wider">Tasks</span>
        <button
          onClick={addTask}
          className="flex items-center gap-1 rounded px-2 py-1 text-xs text-blue-600 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-900/20"
        >
          <Plus className="h-3 w-3" /> Add
        </button>
      </div>

      <div className="space-y-1.5 max-h-64 overflow-y-auto">
        {tasks.map((task, idx) => (
          <div key={task.id} className="rounded border border-ink-200 dark:border-ink-700 bg-white dark:bg-ink-800 p-2 text-xs space-y-1.5">
            <div className="flex items-center gap-1.5">
              <input
                value={task.name}
                onChange={(e) => updateTask(idx, 'name', e.target.value)}
                className="flex-1 rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1.5 py-0.5 text-xs"
                placeholder="Task name"
              />
              <select
                value={task.ifc_task_type}
                onChange={(e) => updateTask(idx, 'ifc_task_type', e.target.value)}
                className="rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs"
              >
                {IFC_TASK_TYPES.map(t => <option key={t} value={t}>{t}</option>)}
              </select>
              <button onClick={() => removeTask(idx)} className="text-red-400 hover:text-red-600"><Trash2 className="h-3 w-3" /></button>
            </div>
            <div className="grid grid-cols-2 gap-1.5">
              <div>
                <label className="text-ink-500 dark:text-ink-400">Start</label>
                <input type="date" value={task.start} onChange={(e) => updateTask(idx, 'start', e.target.value)}
                  className="mt-0.5 w-full rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs" />
              </div>
              <div>
                <label className="text-ink-500 dark:text-ink-400">Finish</label>
                <input type="date" value={task.finish} onChange={(e) => updateTask(idx, 'finish', e.target.value)}
                  className="mt-0.5 w-full rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs" />
              </div>
            </div>
            <div>
              <label className="text-ink-500 dark:text-ink-400">Element IDs (comma-separated)</label>
              <input
                value={task.element_ids.join(', ')}
                onChange={(e) => updateTask(idx, 'element_ids', e.target.value.split(',').map(s => s.trim()).filter(Boolean))}
                className="mt-0.5 w-full rounded border border-ink-200 dark:border-ink-600 bg-transparent px-1 py-0.5 text-xs"
                placeholder="wall-001, col-001"
              />
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main panel
// ---------------------------------------------------------------------------

export default function ConstructionSequencingPanel({ content, projectId, onToast }) {
  // Accept a `content` string (JSON) from the panel registry; merge over defaults.
  // Currently the panel is self-contained (DEMO_TASKS); content can seed
  // an initial tasks list via content.tasks if provided.
  const _contentParsed = (() => { if (!content) return {}; try { return JSON.parse(content) } catch { return {} } })()
  const [tasks, setTasks] = useState(_contentParsed.tasks ?? DEMO_TASKS)
  const [queryDate, setQueryDate] = useState(today())
  const [timeline, setTimeline] = useState(null)
  const [criticalPath, setCriticalPath] = useState([])
  const [validationErrors, setValidationErrors] = useState([])
  const [loading, setLoading] = useState(false)
  const [expanded, setExpanded] = useState(true)
  const [activeTab, setActiveTab] = useState('timeline') // 'timeline' | 'tasks' | 'validation'

  // Derived: project date range for scrubber
  const projectDates = useMemo(() => {
    if (!tasks.length) return { min: today(), max: today() }
    const starts = tasks.map(t => t.start).sort()
    const finishes = tasks.map(t => t.finish).sort()
    return { min: starts[0], max: finishes[finishes.length - 1] }
  }, [tasks])

  const schedule = useMemo(() => ({
    tasks,
    project_start: projectDates.min,
    project_finish: projectDates.max,
    name: '4D Schedule',
  }), [tasks, projectDates])

  const buildTimeline = useCallback(async () => {
    setLoading(true)
    try {
      // Simulate tool call by running logic client-side
      // In production this would call the bim_4d_build_timeline LLM tool
      const result = _computeTimeline(schedule, queryDate)
      setTimeline(result)
      setCriticalPath(_computeCriticalPath(tasks))
    } catch (err) {
      onToast?.(err?.message || '4D timeline computation failed')
    } finally {
      setLoading(false)
    }
  }, [schedule, queryDate, tasks, onToast])

  const validateSchedule = useCallback(() => {
    const errors = []
    const taskIds = new Set(tasks.map(t => t.id))
    tasks.forEach(t => {
      t.predecessors.forEach(p => {
        if (!taskIds.has(p)) errors.push(`Task '${t.id}': predecessor '${p}' not found`)
      })
      if (t.start > t.finish) errors.push(`Task '${t.id}': start after finish`)
    })
    setValidationErrors(errors)
    setActiveTab('validation')
  }, [tasks])

  const summary = useMemo(() => {
    if (!timeline) return { not_started: 0, active: 0, complete: 0 }
    const seen = new Set()
    const counts = { not_started: 0, active: 0, complete: 0 }
    timeline.forEach(e => {
      if (!seen.has(e.element_id)) {
        seen.add(e.element_id)
        counts[e.state] = (counts[e.state] || 0) + 1
      }
    })
    return counts
  }, [timeline])

  return (
    <div className="flex flex-col border border-ink-200 dark:border-ink-700 rounded-lg bg-white dark:bg-ink-900 overflow-hidden">
      {/* Header */}
      <button
        className="flex items-center justify-between px-4 py-3 text-sm font-semibold text-ink-800 dark:text-ink-100 hover:bg-ink-50 dark:hover:bg-ink-800"
        onClick={() => setExpanded(x => !x)}
      >
        <div className="flex items-center gap-2">
          <Calendar className="h-4 w-4 text-blue-500" />
          <span>4D Construction Sequencing</span>
          <span className="text-xs font-normal text-ink-400 dark:text-ink-500">Revit parity · IFC4 IfcTask</span>
        </div>
        {expanded ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
      </button>

      {expanded && (
        <div className="p-4 space-y-4 border-t border-ink-200 dark:border-ink-700">
          {/* Date scrubber */}
          <div className="space-y-1">
            <label className="text-xs font-medium text-ink-600 dark:text-ink-300">
              Query Date: <span className="font-mono text-blue-600 dark:text-blue-400">{queryDate}</span>
            </label>
            <input
              type="range"
              min={projectDates.min}
              max={projectDates.max}
              value={queryDate}
              onChange={(e) => setQueryDate(e.target.value)}
              className="w-full accent-blue-500"
            />
            <div className="flex justify-between text-xs text-ink-400">
              <span>{projectDates.min}</span>
              <span>{projectDates.max}</span>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex gap-2">
            <button
              onClick={buildTimeline}
              disabled={loading}
              className="flex-1 flex items-center justify-center gap-1.5 rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700 disabled:opacity-50"
            >
              {loading ? <span className="animate-spin">⟳</span> : <Zap className="h-3.5 w-3.5" />}
              Build Timeline
            </button>
            <button
              onClick={validateSchedule}
              className="flex items-center gap-1.5 rounded-md border border-ink-300 px-3 py-1.5 text-sm font-medium text-ink-700 hover:bg-ink-50 dark:border-ink-600 dark:text-ink-300 dark:hover:bg-ink-800"
            >
              <ClipboardList className="h-3.5 w-3.5" />
              Validate
            </button>
          </div>

          {/* Summary */}
          {timeline && (
            <div className="flex gap-2">
              <StatBadge label="Not Started" count={summary.not_started} color="bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-300" />
              <StatBadge label="Active" count={summary.active} color="bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300" />
              <StatBadge label="Complete" count={summary.complete} color="bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300" />
            </div>
          )}

          {/* Tabs */}
          <div className="flex border-b border-ink-200 dark:border-ink-700">
            {[['timeline', 'Timeline'], ['tasks', 'Tasks'], ['validation', 'Validation']].map(([id, label]) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`px-3 py-1.5 text-xs font-medium border-b-2 transition-colors ${
                  activeTab === id
                    ? 'border-blue-500 text-blue-600 dark:text-blue-400'
                    : 'border-transparent text-ink-500 hover:text-ink-700 dark:hover:text-ink-300'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {/* Timeline tab */}
          {activeTab === 'timeline' && (
            <div className="space-y-1">
              {!timeline ? (
                <p className="text-xs text-ink-400 dark:text-ink-500 italic">Click "Build Timeline" to compute element states.</p>
              ) : (
                <div className="rounded border border-ink-200 dark:border-ink-700 overflow-hidden">
                  <table className="w-full text-xs">
                    <thead className="bg-ink-50 dark:bg-ink-800">
                      <tr>
                        <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Element</th>
                        <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Task</th>
                        <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">State</th>
                        <th className="px-2 py-1.5 text-left font-medium text-ink-600 dark:text-ink-300">Progress</th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-ink-100 dark:divide-ink-800">
                      {timeline.map((entry, i) => (
                        <tr key={i} className={`hover:bg-ink-50 dark:hover:bg-ink-800/50 ${criticalPath.includes(entry.task_id) ? 'bg-red-50 dark:bg-red-900/10' : ''}`}>
                          <td className="px-2 py-1.5 font-mono">{entry.element_id}</td>
                          <td className="px-2 py-1.5">{entry.task_name}</td>
                          <td className="px-2 py-1.5"><StateBadge state={entry.state} /></td>
                          <td className="px-2 py-1.5">
                            <div className="flex items-center gap-1.5">
                              <ProgressBar pct={entry.progress_pct} state={entry.state} />
                              <span className="text-ink-400">{entry.progress_pct}%</span>
                            </div>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}

          {/* Tasks tab */}
          {activeTab === 'tasks' && (
            <TaskEditor tasks={tasks} onChange={setTasks} />
          )}

          {/* Validation tab */}
          {activeTab === 'validation' && (
            <div className="space-y-2">
              {validationErrors.length === 0 ? (
                <div className="flex items-center gap-2 text-xs text-green-600 dark:text-green-400">
                  <CheckCircle2 className="h-4 w-4" />
                  Schedule is valid
                </div>
              ) : (
                <div className="space-y-1">
                  {validationErrors.map((e, i) => (
                    <div key={i} className="flex items-start gap-1.5 text-xs text-red-600 dark:text-red-400">
                      <AlertCircle className="h-3.5 w-3.5 mt-0.5 shrink-0" />
                      {e}
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Client-side computation (mirrors Python engine — used without backend call)
// ---------------------------------------------------------------------------

function _computeTimeline(schedule, queryDate) {
  const q = new Date(queryDate)
  const entries = []
  for (const task of schedule.tasks) {
    const s = new Date(task.start)
    const f = new Date(task.finish)
    let state, progress
    if (q < s) { state = 'not_started'; progress = 0 }
    else if (q > f) { state = 'complete'; progress = 100 }
    else {
      state = 'active'
      const elapsed = (q - s) / 86400000
      const total = Math.max((f - s) / 86400000, 1)
      progress = Math.round(Math.min(100, elapsed / total * 100) * 10) / 10
    }
    for (const eid of (task.element_ids || [])) {
      entries.push({ element_id: eid, task_id: task.id, task_name: task.name, state, progress_pct: progress, ifc_task_type: task.ifc_task_type, trade: task.trade })
    }
  }
  return entries
}

function _computeCriticalPath(tasks) {
  // Simplified: tasks with no successors or those with longest path
  const taskMap = Object.fromEntries(tasks.map(t => [t.id, t]))
  const successors = Object.fromEntries(tasks.map(t => [t.id, []]))
  tasks.forEach(t => t.predecessors.forEach(p => { if (successors[p]) successors[p].push(t.id) }))
  // Tasks with no successors are "critical" in simplified model
  return tasks.filter(t => successors[t.id].length === 0).map(t => t.id)
}
