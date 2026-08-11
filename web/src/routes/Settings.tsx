import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertCircle, Check, KeyRound, Loader2, Save, Trash2 } from 'lucide-react'
import Layout from '../components/Layout.jsx'
import Card from '../components/Card.jsx'
import Button from '../components/Button.jsx'
import Input from '../components/Input.jsx'
import { api, ApiError } from '../lib/api.js'
import type { ProviderKeysResponse, UsageReport } from '../types/api.js'
import { providerLabel, formatTokens, formatUsd, formatBytes } from '../lib/usageFormat.js'

/**
 * Settings — model provider keys and usage.
 *
 * Kerf can read its LLM keys from environment variables or kerf.toml, but
 * almost nobody who installs an app goes and edits a config file, and changing
 * one that way needs a restart. So keys are stored per user in the database and
 * edited here; config remains the fallback for headless deployments, which is
 * what the "configured on the server" state below reports.
 *
 * Two things this screen must never do: display a saved key (the server only
 * ever sends a mask), and imply that the dollar figures are a bill. Kerf has no
 * billing anywhere — usd_cost is an estimate recorded at call time so you can
 * see what your own provider account is being spent on.
 */

const RANGES = [
  { days: 7, label: '7 days' },
  { days: 30, label: '30 days' },
  { days: 90, label: '90 days' },
]

interface ProviderRowProps {
  provider: string
  saved?: ProviderKeysResponse['keys'][number]
  operatorConfigured: boolean
  onSaved: () => void
}

export function ProviderRow({ provider, saved, operatorConfigured, onSaved }: ProviderRowProps) {
  const [apiKey, setApiKey] = useState('')
  const [baseUrl, setBaseUrl] = useState(saved?.base_url || '')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)

  // Reset the field when the saved value changes (a save or a removal
  // elsewhere in the page), without clobbering what the user is typing.
  const savedBaseUrl = saved?.base_url || ''
  const [lastSavedBaseUrl, setLastSavedBaseUrl] = useState(savedBaseUrl)
  if (savedBaseUrl !== lastSavedBaseUrl) {
    setLastSavedBaseUrl(savedBaseUrl)
    setBaseUrl(savedBaseUrl)
  }

  const save = async (e?: { preventDefault?: () => void }) => {
    e?.preventDefault?.()
    if (busy || !apiKey.trim()) return
    setBusy(true); setErr(null); setMsg(null)
    try {
      await api.saveProviderKey(provider, apiKey.trim(), baseUrl.trim())
      setApiKey('')
      setMsg('Saved.')
      onSaved()
    } catch (e) {
      // The server validates the key against the live provider before storing
      // it, so "invalid" here means the provider rejected it — worth saying
      // plainly rather than as a generic failure.
      const detail = e instanceof ApiError ? e.message : ''
      setErr(
        detail.includes('provider_key_invalid')
          ? `${providerLabel(provider)} rejected that key.`
          : detail.includes('provider_key_validation_failed')
            ? `Could not reach ${providerLabel(provider)} to check the key. Try again.`
            : detail || 'Could not save the key.',
      )
    } finally {
      setBusy(false)
    }
  }

  const remove = async () => {
    setBusy(true); setErr(null); setMsg(null)
    try {
      await api.deleteProviderKey(provider)
      setBaseUrl('')
      onSaved()
    } catch (e) {
      setErr(e instanceof ApiError ? e.message : 'Could not remove the key.')
    } finally {
      setBusy(false)
    }
  }

  const status = saved
    ? saved.readable
      ? { tone: 'ok' as const, text: `Your key ${saved.masked_key}` }
      : { tone: 'warn' as const, text: 'Saved, but unreadable — re-enter it' }
    : operatorConfigured
      ? { tone: 'muted' as const, text: 'Using the server’s key' }
      : { tone: 'muted' as const, text: 'Not configured' }

  return (
    <form
      className="flex flex-col gap-3 py-4 border-b border-ink-800 last:border-b-0"
      onSubmit={save}
      aria-label={`${providerLabel(provider)} API key`}
    >
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <h3 className="text-sm font-medium text-ink-100">{providerLabel(provider)}</h3>
        <span
          className={
            status.tone === 'ok'
              ? 'text-[11px] font-mono text-kerf-300'
              : status.tone === 'warn'
                ? 'text-[11px] font-mono text-amber-300'
                : 'text-[11px] font-mono text-ink-500'
          }
        >
          {status.text}
        </span>
      </div>

      {saved && !saved.readable && (
        <p className="text-[11px] text-amber-200/80 leading-snug">
          This key was encrypted with a different server secret and can no longer be
          read. Entering it again will replace it.
        </p>
      )}

      {err && (
        <div
          role="alert"
          aria-live="assertive"
          className="flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200"
        >
          <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden />
          <span>{err}</span>
        </div>
      )}
      {msg && (
        <div role="status" aria-live="polite" className="flex items-center gap-1.5 text-xs text-kerf-300">
          <Check size={12} aria-hidden />
          {msg}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2">
        <Input
          label="API key"
          type="password"
          autoComplete="off"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          placeholder={saved ? 'Enter a new key to replace' : 'Paste your key'}
        />
        <Input
          label="Base URL (optional)"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="Gateway or compatible endpoint"
        />
      </div>

      <div className="flex flex-wrap justify-end gap-2">
        {saved && (
          <Button type="button" variant="ghost" size="sm" onClick={remove} disabled={busy}>
            <Trash2 size={12} />
            Remove
          </Button>
        )}
        <Button type="submit" variant="primary" size="sm" disabled={busy || !apiKey.trim()}>
          {busy ? <Loader2 size={12} className="animate-spin" /> : <Save size={12} />}
          {busy ? 'Checking…' : 'Save'}
        </Button>
      </div>
    </form>
  )
}

const KIND_LABELS: Record<string, string> = {
  token: 'Chat',
  operator_token: 'Chat (server key)',
  storage: 'Files',
  gpu: 'Compute',
  egress: 'Downloads',
}

/**
 * Where the usage went, by kind.
 *
 * The by-model table below answers "which model", but not every recorded event
 * has one — file uploads and GPU renders are usage too, and on a self-hosted
 * node they are usually the larger number. Rendering only the token rows made
 * the totals above look wrong, because they include everything.
 */
export function KindBreakdown({ report }: { report: UsageReport }) {
  if (report.by_kind.length === 0) return null
  return (
    <div className="mt-5 flex flex-wrap gap-2">
      {report.by_kind.map((k) => (
        <div key={k.kind} className="flex-1 min-w-[150px] rounded-lg border border-ink-800 bg-ink-950 px-3 py-2">
          <p className="text-[11px] text-ink-300">{KIND_LABELS[k.kind] || k.kind}</p>
          <p className="text-sm text-ink-100 tabular-nums">
            {k.kind === 'storage'
              ? formatBytes(k.bytes_delta)
              : `${formatTokens(k.input_tokens + k.output_tokens)} tokens`}
          </p>
          <p className="text-[11px] text-ink-500 tabular-nums">
            {k.events} {k.events === 1 ? 'event' : 'events'}
            {k.usd_cost > 0 && ` · ${formatUsd(k.usd_cost)}`}
          </p>
        </div>
      ))}
    </div>
  )
}

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-ink-800 bg-ink-950 px-3 py-2.5">
      <p className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-500">{label}</p>
      <p className="text-lg font-semibold text-ink-100 tabular-nums">{value}</p>
      {hint && <p className="text-[11px] text-ink-500">{hint}</p>}
    </div>
  )
}

export function UsageChart({ report }: { report: UsageReport }) {
  const peak = useMemo(
    () => Math.max(1, ...report.daily.map((d) => d.input_tokens + d.output_tokens)),
    [report.daily],
  )
  if (report.daily.length === 0) return null

  return (
    <div className="flex items-end gap-1 h-24 mt-1" role="img"
         aria-label={`Daily token use over the last ${report.days} days`}>
      {report.daily.map((d) => {
        const total = d.input_tokens + d.output_tokens
        return (
          <div
            key={d.day}
            className="flex-1 min-w-[3px] bg-kerf-300/40 hover:bg-kerf-300/70 rounded-sm"
            // Zero-token days still get a hairline so the axis reads as a
            // continuous range rather than a gap.
            style={{ height: `${Math.max(2, (total / peak) * 100)}%` }}
            title={`${d.day}: ${formatTokens(total)} tokens, ${formatUsd(d.usd_cost)}`}
          />
        )
      })}
    </div>
  )
}

export default function Settings() {
  const [keys, setKeys] = useState<ProviderKeysResponse | null>(null)
  const [usage, setUsage] = useState<UsageReport | null>(null)
  const [days, setDays] = useState(30)
  const [loadErr, setLoadErr] = useState<string | null>(null)

  const loadKeys = useCallback(() => {
    return api.providerKeys()
      .then(setKeys)
      .catch((e) => {
        setLoadErr(e instanceof ApiError ? e.message : 'Could not load provider keys.')
      })
  }, [])

  useEffect(() => { void loadKeys() }, [loadKeys])

  useEffect(() => {
    let cancelled = false
    api.usage(days)
      .then((r) => { if (!cancelled) setUsage(r) })
      .catch(() => { if (!cancelled) setUsage(null) })
    return () => { cancelled = true }
  }, [days])

  const savedByProvider = useMemo(() => {
    const out: Record<string, ProviderKeysResponse['keys'][number]> = {}
    for (const k of keys?.keys || []) out[k.provider] = k
    return out
  }, [keys])

  return (
    <Layout>
      <div className="max-w-3xl mx-auto">
        <div className="flex items-center gap-3 mb-6">
          <span className="grid place-items-center w-10 h-10 rounded-xl bg-kerf-300/15 border border-kerf-300/30 text-kerf-300">
            <KeyRound size={18} />
          </span>
          <div>
            <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-kerf-300">Account</p>
            <h1 className="font-display text-2xl font-semibold tracking-tight">Settings</h1>
          </div>
        </div>

        {loadErr && (
          <div
            role="alert"
            className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200"
          >
            <AlertCircle size={14} className="mt-0.5 shrink-0" aria-hidden />
            <span>{loadErr}</span>
          </div>
        )}

        <Card className="p-6 mb-6">
          <div className="mb-2">
            <h2 className="font-display text-lg font-semibold tracking-tight">Model providers</h2>
            <p className="text-[12px] text-ink-500 leading-snug">
              Your keys are encrypted before they are stored and are never sent back to
              the browser. A provider with no key of your own falls back to whatever the
              server was configured with.
            </p>
          </div>

          {keys === null ? (
            <p className="py-6 text-sm text-ink-500 flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" aria-hidden />
              Loading…
            </p>
          ) : (
            keys.supported_providers.map((p) => (
              <ProviderRow
                key={p}
                provider={p}
                saved={savedByProvider[p]}
                operatorConfigured={keys.operator_configured.includes(p)}
                onSaved={loadKeys}
              />
            ))
          )}
        </Card>

        <Card className="p-6">
          <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
            <div>
              <h2 className="font-display text-lg font-semibold tracking-tight">Usage</h2>
              <p className="text-[12px] text-ink-500 leading-snug">
                Tokens, storage and compute recorded against your account. Costs are
                estimates from the provider’s published rates — Kerf does not bill for
                anything.
              </p>
            </div>
            <div className="flex gap-1" role="group" aria-label="Usage period">
              {RANGES.map((r) => (
                <button
                  key={r.days}
                  type="button"
                  onClick={() => setDays(r.days)}
                  aria-pressed={days === r.days}
                  className={
                    days === r.days
                      ? 'px-2.5 py-1 rounded-lg text-xs bg-kerf-300/15 border border-kerf-300/30 text-kerf-300'
                      : 'px-2.5 py-1 rounded-lg text-xs border border-ink-800 text-ink-400 hover:text-ink-200'
                  }
                >
                  {r.label}
                </button>
              ))}
            </div>
          </div>

          {usage === null ? (
            <p className="py-6 text-sm text-ink-500 flex items-center gap-2">
              <Loader2 size={14} className="animate-spin" aria-hidden />
              Loading…
            </p>
          ) : usage.totals.events === 0 ? (
            <p className="py-6 text-sm text-ink-500">
              Nothing recorded in this period yet.
            </p>
          ) : (
            <>
              <div className="grid gap-2 grid-cols-2 sm:grid-cols-4">
                <StatTile label="Input" value={formatTokens(usage.totals.input_tokens)} hint="tokens" />
                <StatTile label="Output" value={formatTokens(usage.totals.output_tokens)} hint="tokens" />
                <StatTile label="Est. cost" value={formatUsd(usage.totals.usd_cost)} hint="not a bill" />
                <StatTile label="Storage" value={formatBytes(usage.totals.bytes_delta)} hint="net change" />
              </div>

              <UsageChart report={usage} />

              <KindBreakdown report={usage} />

              {usage.by_model.length > 0 && (
                <div className="mt-6 overflow-x-auto">
                  <table className="w-full text-sm">
                    <caption className="sr-only">Usage by model</caption>
                    <thead>
                      <tr className="text-[10px] font-mono uppercase tracking-[0.18em] text-ink-500">
                        <th scope="col" className="text-left font-normal pb-1.5">Model</th>
                        <th scope="col" className="text-right font-normal pb-1.5">Calls</th>
                        <th scope="col" className="text-right font-normal pb-1.5">In</th>
                        <th scope="col" className="text-right font-normal pb-1.5">Out</th>
                        <th scope="col" className="text-right font-normal pb-1.5">Est. cost</th>
                      </tr>
                    </thead>
                    <tbody>
                      {usage.by_model.map((m) => (
                        <tr key={m.model} className="border-t border-ink-800">
                          <td className="py-1.5 font-mono text-[12px] text-ink-200">{m.model}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-300">{m.events}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-300">{formatTokens(m.input_tokens)}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-300">{formatTokens(m.output_tokens)}</td>
                          <td className="py-1.5 text-right tabular-nums text-ink-200">{formatUsd(m.usd_cost)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </>
          )}
        </Card>
      </div>
    </Layout>
  )
}
