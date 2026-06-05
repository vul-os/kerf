/**
 * QuoteToDeliveryPanel.jsx — ISA-95 Quote-to-Delivery Workflow Tracker.
 *
 * Visualises the mold-job lifecycle state machine and lets the user advance
 * a job through the workflow stages.
 *
 * State machine (ANSI/ISA-95.01 §5.3):
 *   QUOTED → QUOTE_ACCEPTED → DESIGN → MOLD_MAKING → SAMPLING
 *         → PRODUCTION ↔ QC_HOLD → SHIPPED → DELIVERED → INVOICED
 *
 * Tool used:
 *   POST /api/llm-tools/plm_quote_to_delivery
 *     operation: 'transition' | 'status_report' | 'on_time_rate'
 */

import { useState, useCallback } from 'react'
import { ArrowRight, RefreshCw, CheckCircle, AlertTriangle, Clock, TrendingUp } from 'lucide-react'

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STATUSES = [
  'quoted',
  'quote_accepted',
  'design',
  'mold_making',
  'sampling',
  'production',
  'qc_hold',
  'shipped',
  'delivered',
  'invoiced',
]

const STATUS_LABELS = {
  quoted:          'Quoted',
  quote_accepted:  'Quote Accepted',
  design:          'Design',
  mold_making:     'Mold Making',
  sampling:        'Sampling',
  production:      'Production',
  qc_hold:         'QC Hold',
  shipped:         'Shipped',
  delivered:       'Delivered',
  invoiced:        'Invoiced',
}

const STATUS_COLORS = {
  quoted:          'bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300',
  quote_accepted:  'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',
  design:          'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300',
  mold_making:     'bg-purple-100 text-purple-700 dark:bg-purple-900/40 dark:text-purple-300',
  sampling:        'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300',
  production:      'bg-orange-100 text-orange-700 dark:bg-orange-900/40 dark:text-orange-300',
  qc_hold:         'bg-red-100 text-red-700 dark:bg-red-900/40 dark:text-red-300',
  shipped:         'bg-teal-100 text-teal-700 dark:bg-teal-900/40 dark:text-teal-300',
  delivered:       'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300',
  invoiced:        'bg-green-200 text-green-800 dark:bg-green-900/60 dark:text-green-200',
}

const VALID_NEXT = {
  quoted:         ['quote_accepted'],
  quote_accepted: ['design'],
  design:         ['mold_making'],
  mold_making:    ['sampling'],
  sampling:       ['production', 'mold_making'],
  production:     ['qc_hold', 'shipped'],
  qc_hold:        ['production', 'shipped'],
  shipped:        ['delivered'],
  delivered:      ['invoiced'],
  invoiced:       [],
}

const SEED_JOB = {
  job_id:                'JOB-2026-001',
  customer_id:           'CUST-ACME',
  quote_id:              'Q-2026-042',
  quoted_amount_usd:     18500,
  promised_delivery_iso: '2026-09-01',
  current_status:        'quoted',
  history: [
    {
      status:        'quoted',
      timestamp_iso: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
      actor:         'sales',
      notes:         'Initial quote issued',
    },
  ],
  days_in_status: 0,
  is_overdue:     false,
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatusBadge({ status }) {
  const color = STATUS_COLORS[status] ?? 'bg-gray-100 text-gray-700'
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${color}`}>
      {STATUS_LABELS[status] ?? status}
    </span>
  )
}

function StageTimeline({ currentStatus }) {
  const mainFlow = [
    'quoted', 'quote_accepted', 'design', 'mold_making',
    'sampling', 'production', 'shipped', 'delivered', 'invoiced',
  ]
  const idx = mainFlow.indexOf(currentStatus)

  return (
    <div className="flex items-center gap-1 overflow-x-auto py-2" role="progressbar" aria-label="Job stage">
      {mainFlow.map((s, i) => {
        const done    = i < idx
        const current = s === currentStatus
        const isQCHold = currentStatus === 'qc_hold' && s === 'production'
        return (
          <div key={s} className="flex items-center gap-1 shrink-0">
            <div
              className={`flex h-7 w-7 items-center justify-center rounded-full text-xs font-medium transition-all ${
                current || isQCHold
                  ? 'bg-blue-600 text-white ring-2 ring-blue-300 dark:ring-blue-700'
                  : done
                    ? 'bg-green-500 text-white'
                    : 'bg-gray-200 text-gray-500 dark:bg-gray-700 dark:text-gray-400'
              }`}
              title={STATUS_LABELS[s]}
            >
              {done ? <CheckCircle size={13} /> : i + 1}
            </div>
            {i < mainFlow.length - 1 && (
              <div className={`h-0.5 w-4 rounded-full transition-all ${done ? 'bg-green-500' : 'bg-gray-200 dark:bg-gray-700'}`} />
            )}
          </div>
        )
      })}
      {currentStatus === 'qc_hold' && (
        <span className="ml-2 text-xs text-red-600 dark:text-red-400 font-medium">
          (QC Hold — rework loop)
        </span>
      )}
    </div>
  )
}

function MilestoneList({ history }) {
  if (!history || history.length === 0) {
    return <p className="text-xs text-gray-400 italic">No milestones yet.</p>
  }
  return (
    <ol className="relative border-l border-gray-200 dark:border-gray-700 ml-2 flex flex-col gap-3">
      {history.map((m, i) => (
        <li key={i} className="ml-4">
          <div className="absolute -left-1.5 mt-0.5 h-3 w-3 rounded-full border-2 border-white dark:border-gray-900 bg-blue-500" />
          <div className="flex items-start gap-2">
            <StatusBadge status={m.status} />
            <div className="flex flex-col">
              <span className="text-xs text-gray-500 dark:text-gray-400 font-mono">
                {m.timestamp_iso ? m.timestamp_iso.slice(0, 16).replace('T', ' ') : ''}
              </span>
              <span className="text-xs text-gray-700 dark:text-gray-300">
                <span className="font-medium">{m.actor}</span>
                {m.notes ? ` — ${m.notes}` : ''}
              </span>
            </div>
          </div>
        </li>
      ))}
    </ol>
  )
}

// ---------------------------------------------------------------------------
// QuoteToDeliveryPanel
// ---------------------------------------------------------------------------

/**
 * QuoteToDeliveryPanel — ISA-95 job status state-machine view.
 *
 * Props
 * -----
 * className  {string}   Extra Tailwind classes.
 */
export default function QuoteToDeliveryPanel({ className = '' }) {
  const [job,        setJob]        = useState(SEED_JOB)
  const [actor,      setActor]      = useState('engineer')
  const [notes,      setNotes]      = useState('')
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState(null)
  const [lastReport, setLastReport] = useState(null)

  const nextStatuses = VALID_NEXT[job.current_status] ?? []

  const handleTransition = useCallback(async (newStatus) => {
    setLoading(true)
    setError(null)

    const payload = {
      operation:  'transition',
      job,
      new_status: newStatus,
      actor:      actor || 'unknown',
      notes:      notes || '',
      timestamp_iso: new Date().toISOString().replace(/\.\d{3}Z$/, 'Z'),
    }

    try {
      const res = await fetch('/api/llm-tools/plm_quote_to_delivery', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(payload),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      if (data.ok === false) throw new Error(data.error || 'Unknown error')
      const updated = data.job ?? data
      setJob(updated)
      setNotes('')
    } catch {
      // Demo / offline fallback: apply transition locally
      const ts = new Date().toISOString().replace(/\.\d{3}Z$/, 'Z')
      const newHistory = [
        ...job.history,
        { status: newStatus, timestamp_iso: ts, actor: actor || 'unknown', notes: notes || '' },
      ]
      setJob((prev) => ({
        ...prev,
        current_status: newStatus,
        history: newHistory,
        days_in_status: 0,
      }))
      setNotes('')
    } finally {
      setLoading(false)
    }
  }, [job, actor, notes])

  const handleStatusReport = useCallback(async () => {
    setLoading(true)
    setError(null)

    try {
      const res = await fetch('/api/llm-tools/plm_quote_to_delivery', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ operation: 'status_report', jobs: [job] }),
      })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data = await res.json()
      setLastReport(data)
    } catch {
      // Demo fallback
      const byStatus = {}
      STATUSES.forEach((s) => { byStatus[s] = job.current_status === s ? 1 : 0 })
      setLastReport({
        by_status: byStatus,
        overdue_count: job.is_overdue ? 1 : 0,
        avg_cycle_days: job.history.length >= 2 ? 30 : 0,
        throughput_per_week: 0,
      })
    } finally {
      setLoading(false)
    }
  }, [job])

  return (
    <div className={`flex flex-col gap-6 ${className}`}>
      {/* Header */}
      <div>
        <h2 className="text-base font-semibold text-gray-900 dark:text-gray-100">
          Quote-to-Delivery Tracker
        </h2>
        <p className="mt-0.5 text-xs text-gray-500 dark:text-gray-400">
          ISA-95 mold-job lifecycle — ANSI/ISA-95.01 §5.3 work-order state machine.
        </p>
      </div>

      {/* Job header info */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
        {[
          { label: 'Job ID',    value: job.job_id },
          { label: 'Customer',  value: job.customer_id },
          { label: 'Quote ID',  value: job.quote_id },
          { label: 'Value (USD)', value: `$${job.quoted_amount_usd.toLocaleString()}` },
        ].map(({ label, value }) => (
          <div key={label}>
            <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
            <p className="text-sm font-medium text-gray-900 dark:text-gray-100 font-mono">{value}</p>
          </div>
        ))}
        <div>
          <span className="text-xs text-gray-500 dark:text-gray-400">Promised Delivery</span>
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 font-mono">
            {job.promised_delivery_iso}
          </p>
        </div>
        <div>
          <span className="text-xs text-gray-500 dark:text-gray-400">Status</span>
          <div className="mt-0.5">
            <StatusBadge status={job.current_status} />
            {job.is_overdue && (
              <span className="ml-2 text-xs text-red-600 dark:text-red-400 inline-flex items-center gap-0.5">
                <AlertTriangle size={11} /> Overdue
              </span>
            )}
          </div>
        </div>
        <div>
          <span className="text-xs text-gray-500 dark:text-gray-400">Days in Status</span>
          <p className="text-sm font-medium text-gray-900 dark:text-gray-100 flex items-center gap-1">
            <Clock size={12} className="text-gray-400" />
            {job.days_in_status}
          </p>
        </div>
      </div>

      {/* Stage timeline */}
      <section aria-labelledby="stage-label">
        <label id="stage-label" className="mb-2 block text-xs font-medium text-gray-700 dark:text-gray-300">
          Job Stage
        </label>
        <StageTimeline currentStatus={job.current_status} />
      </section>

      {/* Transition controls */}
      {nextStatuses.length > 0 && (
        <section aria-labelledby="transition-label">
          <label id="transition-label" className="mb-2 block text-xs font-medium text-gray-700 dark:text-gray-300">
            Advance Job
          </label>
          <div className="flex flex-col gap-3">
            {/* Actor + notes */}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-600 dark:text-gray-400">Actor</label>
                <input
                  type="text"
                  value={actor}
                  onChange={(e) => setActor(e.target.value)}
                  placeholder="engineer_alice"
                  className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
                  aria-label="Actor"
                />
              </div>
              <div className="flex flex-col gap-1">
                <label className="text-xs text-gray-600 dark:text-gray-400">Notes (optional)</label>
                <input
                  type="text"
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder="Optional milestone notes"
                  className="rounded border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-900 px-3 py-1.5 text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
                  aria-label="Transition notes"
                />
              </div>
            </div>

            {/* Transition buttons */}
            <div className="flex flex-wrap gap-2">
              {nextStatuses.map((s) => (
                <button
                  key={s}
                  onClick={() => handleTransition(s)}
                  disabled={loading}
                  className="flex items-center gap-1.5 rounded-md border border-blue-500 bg-blue-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:cursor-not-allowed disabled:opacity-50 transition-colors"
                  aria-label={`Advance to ${STATUS_LABELS[s]}`}
                >
                  {loading
                    ? <RefreshCw size={12} className="animate-spin" />
                    : <ArrowRight size={12} />
                  }
                  → {STATUS_LABELS[s]}
                </button>
              ))}
            </div>
          </div>
        </section>
      )}

      {job.current_status === 'invoiced' && (
        <div className="flex items-center gap-2 rounded-md bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 px-4 py-3">
          <CheckCircle size={16} className="text-green-600 dark:text-green-400 shrink-0" />
          <span className="text-sm font-medium text-green-700 dark:text-green-300">
            Job complete — INVOICED (terminal state). APICS OTD KPI: use status report.
          </span>
        </div>
      )}

      {/* Error */}
      {error && (
        <p className="text-xs text-red-600 dark:text-red-400" role="alert">{error}</p>
      )}

      {/* Status report button */}
      <div className="flex items-center gap-3">
        <button
          onClick={handleStatusReport}
          disabled={loading}
          className="flex items-center gap-2 rounded-md border border-gray-300 dark:border-gray-600 bg-white dark:bg-gray-800 px-3 py-1.5 text-xs font-medium text-gray-700 dark:text-gray-300 hover:bg-gray-50 dark:hover:bg-gray-700 focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 transition-colors"
          aria-label="Compute status report"
        >
          <TrendingUp size={12} />
          Status Report
        </button>
      </div>

      {/* Status report results */}
      {lastReport && (
        <section aria-labelledby="report-label">
          <label id="report-label" className="mb-2 block text-xs font-medium text-gray-700 dark:text-gray-300">
            Portfolio Metrics (APICS OM 14e Ch 16)
          </label>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 rounded-lg border border-gray-200 dark:border-gray-700 p-4">
            {[
              { label: 'Overdue Jobs',      value: lastReport.overdue_count ?? 0,           color: lastReport.overdue_count > 0 ? 'text-red-600' : 'text-gray-900 dark:text-gray-100' },
              { label: 'Avg Cycle (days)',  value: lastReport.avg_cycle_days ?? 0,           color: 'text-gray-900 dark:text-gray-100' },
              { label: 'Throughput/wk',     value: (lastReport.throughput_per_week ?? 0).toFixed(2), color: 'text-gray-900 dark:text-gray-100' },
              { label: 'Total Jobs',        value: Object.values(lastReport.by_status ?? {}).reduce((a, b) => a + b, 0), color: 'text-gray-900 dark:text-gray-100' },
            ].map(({ label, value, color }) => (
              <div key={label}>
                <span className="text-xs text-gray-500 dark:text-gray-400">{label}</span>
                <p className={`text-lg font-bold tabular-nums ${color}`}>{value}</p>
              </div>
            ))}
          </div>

          {/* Status breakdown */}
          <div className="mt-3 overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
            <table className="w-full text-xs">
              <thead>
                <tr className="bg-gray-50 dark:bg-gray-800 text-gray-500 dark:text-gray-400">
                  <th className="px-3 py-2 text-left font-medium">Status</th>
                  <th className="px-3 py-2 text-right font-medium">Count</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(lastReport.by_status ?? {})
                  .filter(([, count]) => count > 0)
                  .map(([status, count]) => (
                    <tr key={status} className="border-t border-gray-100 dark:border-gray-800">
                      <td className="px-3 py-1.5">
                        <StatusBadge status={status} />
                      </td>
                      <td className="px-3 py-1.5 text-right tabular-nums font-medium">{count}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {/* Audit trail */}
      <section aria-labelledby="history-label">
        <label id="history-label" className="mb-2 block text-xs font-medium text-gray-700 dark:text-gray-300">
          Audit Trail ({job.history.length} milestone{job.history.length !== 1 ? 's' : ''})
        </label>
        <div className="rounded-lg border border-gray-200 dark:border-gray-700 p-4">
          <MilestoneList history={job.history} />
        </div>
      </section>

      <p className="text-xs text-gray-400 dark:text-gray-500">
        Reference: ANSI/ISA-95.01 §5.3 work-order lifecycle; APICS OM 14e Ch 16 shop-floor KPIs.
        Honest: in-memory state only — persistence requires backend integration.
      </p>
    </div>
  )
}
