// AdminMargin — operator-only break-even monitoring page (T-408).
//
// Mounted at /admin/margin (admin role only). Fetches GET /api/admin/margin
// for the selected month and renders:
//   - Fixed cost vs realised gross margin
//   - Per-kind revenue/COGS breakdown
//   - Break-even seat count at Studio ($9/mo) pricing
//
// Security note: backend re-checks admin role on every request; this is
// purely a UX gate.

import { useEffect, useState, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { TrendingUp, DollarSign, AlertTriangle, Loader2, RefreshCw, ChevronLeft, ChevronRight } from 'lucide-react'
import Layout from '../components/Layout.jsx'
import { api } from '../lib/api.js'
import { useAuth } from '../store/auth.js'

const KIND_LABELS = {
  token: 'LLM tokens',
  storage: 'Storage',
  gpu: 'GPU compute',
  egress: 'Egress',
  operator_token: 'Operator tokens',
}

function fmt(n, digits = 2) {
  if (n == null) return '—'
  return `$${Number(n).toFixed(digits)}`
}

function fmtPct(n) {
  if (n == null) return '—'
  return `${Number(n).toFixed(2)} %`
}

function prevMonth(ym) {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m - 2, 1) // m-2 because month is 0-indexed
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function nextMonth(ym) {
  const [y, m] = ym.split('-').map(Number)
  const d = new Date(y, m, 1)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

function currentMonthStr() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`
}

export default function AdminMargin() {
  const user = useAuth((s) => s.user)
  const accessToken = useAuth((s) => s.accessToken)
  const navigate = useNavigate()
  const [month, setMonth] = useState(currentMonthStr)
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  // Gate: admin only
  useEffect(() => {
    if (!accessToken) return
    if (user && user.account_role !== 'admin' && user.account_role !== 'system') {
      navigate('/projects', { replace: true, state: { toast: 'Admin access required.' } })
    }
  }, [user, accessToken, navigate])

  const load = useCallback(async (m) => {
    setLoading(true)
    setError(null)
    try {
      const out = await api.admin.getMargin(m)
      setData(out)
    } catch (err) {
      if (err?.status === 403) {
        setError('Admin access required.')
      } else {
        setError(err?.message || 'Failed to load margin data.')
      }
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    if (accessToken) load(month)
  }, [accessToken, month, load])

  const marginColor = data?.totals?.gross_margin_usd > 0
    ? 'text-emerald-400'
    : data?.totals?.gross_margin_usd < 0
    ? 'text-red-400'
    : 'text-ink-400'

  const afterFixedColor = data?.margin_after_fixed_usd > 0
    ? 'text-emerald-400'
    : 'text-red-400'

  return (
    <Layout>
      <div className="max-w-2xl">
        {/* Header */}
        <header className="mb-6">
          <div className="flex items-center gap-2 mb-1">
            <TrendingUp size={18} className="text-kerf-300" />
            <h1 className="text-xl font-semibold text-ink-100">Break-even Monitor</h1>
          </div>
          <p className="text-sm text-ink-400">
            Realised gross margin from <code className="text-ink-300 font-mono text-xs">usage_events</code> vs fixed Koyeb infrastructure cost.
            Goal: ROADMAP §7.1 — make the break-even target visible in under a minute.
          </p>
        </header>

        {/* Month navigation */}
        <div className="flex items-center gap-2 mb-6">
          <button
            type="button"
            onClick={() => setMonth(prevMonth(month))}
            className="p-1.5 rounded-md text-ink-400 hover:text-ink-100 hover:bg-ink-800"
            aria-label="Previous month"
          >
            <ChevronLeft size={15} />
          </button>
          <span className="text-sm font-mono text-ink-200 min-w-[6rem] text-center">{month}</span>
          <button
            type="button"
            onClick={() => setMonth(nextMonth(month))}
            className="p-1.5 rounded-md text-ink-400 hover:text-ink-100 hover:bg-ink-800"
            aria-label="Next month"
          >
            <ChevronRight size={15} />
          </button>
          <button
            type="button"
            onClick={() => load(month)}
            disabled={loading}
            className="ml-2 p-1.5 rounded-md text-ink-400 hover:text-ink-100 hover:bg-ink-800 disabled:opacity-40"
            aria-label="Refresh"
          >
            <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>

        {/* Error */}
        {error && (
          <div className="mb-4 rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 flex items-start gap-2">
            <AlertTriangle size={14} className="text-amber-400 mt-0.5 flex-shrink-0" />
            <span className="text-sm text-amber-200">{error}</span>
          </div>
        )}

        {/* Loading skeleton */}
        {loading && !data && (
          <div className="space-y-3">
            {[0, 1, 2].map((i) => (
              <div key={i} className="h-16 rounded-lg border border-ink-800 bg-ink-900 animate-pulse" />
            ))}
          </div>
        )}

        {/* Data */}
        {data && !loading && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-6">
              <StatCard label="Revenue" value={fmt(data.totals?.revenue_usd)} />
              <StatCard label="COGS" value={fmt(data.totals?.cogs_usd)} />
              <StatCard label="Gross Margin" value={fmt(data.totals?.gross_margin_usd)} valueClass={marginColor} />
              <StatCard label="Margin %" value={fmtPct(data.margin_pct)} valueClass={data.margin_pct != null ? marginColor : 'text-ink-500'} />
            </div>

            {/* Fixed cost vs margin */}
            <div className="rounded-lg border border-ink-800 bg-ink-900/60 px-4 py-3 mb-4 flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
              <div>
                <div className="text-[10px] uppercase tracking-wider text-ink-500 font-medium mb-0.5">Fixed cost (Koyeb)</div>
                <div className="text-xl font-mono font-semibold text-ink-100">{fmt(data.fixed_cost_usd)}<span className="text-xs text-ink-500 font-sans font-normal ml-1">/mo</span></div>
              </div>
              <div className="hidden sm:block text-ink-700 text-xl">−</div>
              <div>
                <div className="text-[10px] uppercase tracking-wider text-ink-500 font-medium mb-0.5">After fixed costs</div>
                <div className={`text-xl font-mono font-semibold ${afterFixedColor}`}>
                  {fmt(data.margin_after_fixed_usd)}
                  <span className="text-xs text-ink-500 font-sans font-normal ml-1">/mo</span>
                </div>
              </div>
              <div className="sm:ml-auto text-right">
                <div className="text-[10px] uppercase tracking-wider text-ink-500 font-medium mb-0.5">Break-even (Studio seats)</div>
                <div className="text-xl font-mono font-semibold text-ink-100">
                  {data.break_even_seats != null ? data.break_even_seats : '—'}
                  {data.break_even_seats != null && (
                    <span className="text-xs text-ink-500 font-sans font-normal ml-1">× $9/mo</span>
                  )}
                </div>
              </div>
            </div>

            {/* Per-kind breakdown */}
            {data.by_kind?.length > 0 ? (
              <div className="rounded-lg border border-ink-800 overflow-hidden">
                <table className="w-full text-xs">
                  <thead>
                    <tr className="border-b border-ink-800 bg-ink-900/80">
                      <th className="px-3 py-2 text-left text-ink-500 font-medium uppercase tracking-wider text-[10px]">Kind</th>
                      <th className="px-3 py-2 text-right text-ink-500 font-medium uppercase tracking-wider text-[10px]">Revenue</th>
                      <th className="px-3 py-2 text-right text-ink-500 font-medium uppercase tracking-wider text-[10px]">COGS</th>
                      <th className="px-3 py-2 text-right text-ink-500 font-medium uppercase tracking-wider text-[10px]">Margin</th>
                      <th className="px-3 py-2 text-right text-ink-500 font-medium uppercase tracking-wider text-[10px]">Events</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-ink-800/60">
                    {data.by_kind.map((row) => {
                      const m = row.gross_margin_usd
                      const mc = m > 0 ? 'text-emerald-400' : m < 0 ? 'text-red-400' : 'text-ink-400'
                      return (
                        <tr key={row.kind} className="hover:bg-ink-900/40">
                          <td className="px-3 py-2 text-ink-200 font-medium">
                            {KIND_LABELS[row.kind] || row.kind}
                          </td>
                          <td className="px-3 py-2 text-right text-ink-300 font-mono">{fmt(row.revenue_usd)}</td>
                          <td className="px-3 py-2 text-right text-ink-400 font-mono">{fmt(row.cogs_usd)}</td>
                          <td className={`px-3 py-2 text-right font-mono font-semibold ${mc}`}>{fmt(row.gross_margin_usd)}</td>
                          <td className="px-3 py-2 text-right text-ink-500 font-mono">{row.event_count.toLocaleString()}</td>
                        </tr>
                      )
                    })}
                  </tbody>
                  {data.by_kind.length > 1 && (
                    <tfoot>
                      <tr className="border-t border-ink-700 bg-ink-900/80">
                        <td className="px-3 py-2 text-ink-400 font-semibold text-[10px] uppercase tracking-wider">Total</td>
                        <td className="px-3 py-2 text-right text-ink-200 font-mono font-semibold">{fmt(data.totals.revenue_usd)}</td>
                        <td className="px-3 py-2 text-right text-ink-300 font-mono font-semibold">{fmt(data.totals.cogs_usd)}</td>
                        <td className={`px-3 py-2 text-right font-mono font-semibold ${marginColor}`}>{fmt(data.totals.gross_margin_usd)}</td>
                        <td className="px-3 py-2 text-right text-ink-500 font-mono font-semibold">{data.totals.event_count.toLocaleString()}</td>
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            ) : (
              <div className="text-sm text-ink-500 italic border border-ink-800 rounded-lg px-4 py-6 text-center">
                No usage events for {month}.
              </div>
            )}
          </>
        )}
      </div>
    </Layout>
  )
}

function StatCard({ label, value, valueClass = 'text-ink-100' }) {
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-900/50 px-3 py-2.5">
      <div className="text-[10px] uppercase tracking-wider text-ink-500 font-medium mb-1">{label}</div>
      <div className={`text-lg font-mono font-semibold ${valueClass}`}>{value}</div>
    </div>
  )
}
