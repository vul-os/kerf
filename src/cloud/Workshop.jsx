// Workshop — the distributed Workshop. Loaded at /workshop.
//
// Per decisions.md's 2026-07-17 "Final form" ADR and
// docs/distributed-workshop.md: there is no central Workshop server. A
// workshop is client-side state — the set of author feeds ("follows") you
// choose to follow — crawled and rendered here as a browsable, derived
// index (GET /api/pub/workshop). This is a core MIT node capability and is
// never gated behind useCloudConfig().cloudEnabled.
//
// Two views:
//   Browse  — cards for every announcement visible across followed feeds,
//             each with an honest availability badge and a Pin/Unpin toggle.
//   Feeds   — manage the set of feeds that make up "your workshop".

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  AlertTriangle, CheckCircle2, CircleDot, Loader2, Pin, PinOff,
  Plus, Radio, Sparkles, Tag, Trash2, Users, WifiOff,
} from 'lucide-react'
import Layout from '../components/Layout.jsx'
import Card from '../components/Card.jsx'
import Button from '../components/Button.jsx'
import Input from '../components/Input.jsx'
import { ApiError } from '../lib/api.js'
import { pub } from './api.js'

const KIND_LABELS = {
  part: 'Part',
  assembly: 'Assembly',
  pcb: 'PCB',
  schematic: 'Schematic',
  drawing: 'Drawing',
  dataset: 'Dataset',
  doc: 'Doc',
}

function relativeTime(iso) {
  if (!iso) return 'never'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const diff = Date.now() - t
  const sec = Math.round(diff / 1000)
  if (sec < 45) return 'just now'
  const min = Math.round(sec / 60)
  if (min < 60) return `${min}m ago`
  const hr = Math.round(min / 60)
  if (hr < 24) return `${hr}h ago`
  const day = Math.round(hr / 24)
  if (day < 30) return `${day}d ago`
  const mo = Math.round(day / 30)
  if (mo < 12) return `${mo}mo ago`
  return `${Math.round(mo / 12)}y ago`
}

function truncatePub(key) {
  if (!key) return ''
  if (key.length <= 14) return key
  return `${key.slice(0, 8)}…${key.slice(-6)}`
}

// AvailabilityBadge — the four honest states from docs/distributed-workshop.md.
// No fake availability (no spinner masquerading as "it's there"), no silent
// disappearance (stale/unreachable stays visible with its real state).
export function AvailabilityBadge({ availability }) {
  const status = availability?.status || 'unreachable'
  const holders = availability?.holders
  const verified = availability?.last_verified

  const configs = {
    'on-node': {
      icon: CheckCircle2,
      label: 'On this node',
      cls: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
    },
    available: {
      icon: Radio,
      label: `Available — ${holders ?? 0} holder${holders === 1 ? '' : 's'}, verified ${relativeTime(verified)}`,
      cls: 'bg-sky-500/15 text-sky-300 border-sky-500/30',
    },
    stale: {
      icon: CircleDot,
      label: `Stale — last seen ${relativeTime(verified)}`,
      cls: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
    },
    unreachable: {
      icon: WifiOff,
      label: 'Unreachable',
      cls: 'bg-red-500/15 text-red-300 border-red-500/30',
    },
  }
  const c = configs[status] || configs.unreachable
  const Icon = c.icon
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2 py-1 rounded-md text-[10px] font-mono border ${c.cls}`}
      data-testid="availability-badge"
      data-status={status}
      title={c.label}
    >
      <Icon size={11} className="shrink-0" />
      <span className="truncate">{c.label}</span>
    </span>
  )
}

export function WorkshopCard({ item, publisherLabel, superseded, onTogglePin, pinBusy }) {
  const meta = item.meta || {}
  const deprecated = !!meta.deprecated
  const tags = Array.isArray(meta.tags) ? meta.tags : []

  return (
    <Card className="flex flex-col overflow-hidden" data-testid="workshop-card">
      <div className="p-4 flex flex-col gap-3 flex-1">
        <div className="flex items-start justify-between gap-2">
          <div className="min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h3 className="font-display text-base font-semibold tracking-tight text-ink-100 truncate">
                {meta.name || 'Untitled'}
              </h3>
              {superseded && (
                <span className="px-1.5 py-0.5 rounded text-[9px] uppercase tracking-wider bg-ink-800 text-ink-400 border border-ink-700">
                  Superseded
                </span>
              )}
            </div>
            <p className="mt-1 text-xs text-ink-400 line-clamp-2">
              {meta.description || 'No description.'}
            </p>
          </div>
        </div>

        {deprecated && (
          <div
            className="flex items-start gap-2 rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-2 text-[11px] text-amber-200"
            role="alert"
            data-testid="deprecated-banner"
          >
            <AlertTriangle size={12} className="mt-0.5 shrink-0" />
            <span>Deprecated{meta.deprecated_reason ? ` — ${meta.deprecated_reason}` : ''}</span>
          </div>
        )}

        <div className="flex items-center gap-1.5 flex-wrap text-[10px] font-mono">
          {meta.artifact_kind && (
            <span className="px-1.5 py-0.5 rounded bg-ink-800 text-ink-300 border border-ink-700 uppercase tracking-wide">
              {KIND_LABELS[meta.artifact_kind] || meta.artifact_kind}
            </span>
          )}
          {meta.license && (
            <span className="px-1.5 py-0.5 rounded bg-ink-800 text-kerf-300 border border-ink-700">
              {meta.license}
            </span>
          )}
          {meta.units && (
            <span className="px-1.5 py-0.5 rounded bg-ink-800 text-ink-400 border border-ink-700">
              {meta.units}
            </span>
          )}
        </div>

        {tags.length > 0 && (
          <div className="flex items-center gap-1 flex-wrap">
            {tags.slice(0, 4).map((t) => (
              <span
                key={t}
                className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] text-ink-400 bg-ink-850/60 border border-ink-800"
              >
                <Tag size={9} /> {t}
              </span>
            ))}
          </div>
        )}

        <div className="flex items-center justify-between text-[11px] text-ink-400 mt-auto pt-2 border-t border-ink-800">
          <span className="truncate" title={item.pub}>
            {publisherLabel || truncatePub(item.pub)}
          </span>
          <span className="font-mono text-[10px] text-ink-500 shrink-0">
            {relativeTime(item.ts)}
          </span>
        </div>

        <AvailabilityBadge availability={item.availability} />

        <Button
          size="sm"
          variant={item.pinned ? 'secondary' : 'ghost'}
          disabled={pinBusy}
          onClick={() => onTogglePin(item)}
          data-testid="pin-toggle"
        >
          {pinBusy
            ? <Loader2 size={13} className="animate-spin" />
            : item.pinned ? <PinOff size={13} /> : <Pin size={13} />}
          {item.pinned ? 'Unpin' : 'Pin'}
        </Button>
      </div>
    </Card>
  )
}

export function BrowseEmptyState({ hasFollows, onGoToFeeds }) {
  if (!hasFollows) {
    return (
      <Card className="p-10 text-center" data-testid="workshop-empty-no-follows">
        <div className="mx-auto grid place-items-center w-12 h-12 rounded-xl bg-ink-800 border border-ink-700">
          <Users size={20} className="text-kerf-300" aria-hidden="true" />
        </div>
        <h3 className="mt-4 font-display text-lg font-semibold tracking-tight">
          A workshop is the set of feeds you follow
        </h3>
        <p className="mt-1 text-sm text-ink-400 max-w-sm mx-auto">
          There&apos;s no central Workshop server — follow a publisher&apos;s
          feed to add their parts, assemblies, and drawings to your browse
          list.
        </p>
        <div className="mt-4">
          <Button variant="primary" size="sm" onClick={onGoToFeeds}>
            <Plus size={14} /> Add feed
          </Button>
        </div>
      </Card>
    )
  }
  return (
    <Card className="p-10 text-center" data-testid="workshop-empty">
      <div className="mx-auto grid place-items-center w-12 h-12 rounded-xl bg-ink-800 border border-ink-700">
        <Sparkles size={20} className="text-kerf-300" aria-hidden="true" />
      </div>
      <h3 className="mt-4 font-display text-lg font-semibold tracking-tight">
        Nothing published on your followed feeds yet
      </h3>
      <p className="mt-1 text-sm text-ink-400">
        Publish a project from the editor, or follow more feeds.
      </p>
    </Card>
  )
}

export function FollowsPanel({ follows, loading, error, onAdd, onRemove }) {
  const [pubKey, setPubKey] = useState('')
  const [label, setLabel] = useState('')
  const [gatewayUrl, setGatewayUrl] = useState('')
  const [adding, setAdding] = useState(false)
  const [addError, setAddError] = useState(null)
  const [removing, setRemoving] = useState(null)

  const submit = async (e) => {
    e?.preventDefault?.()
    if (!pubKey.trim() || !gatewayUrl.trim()) {
      setAddError('A publisher key and gateway URL are both required.')
      return
    }
    setAdding(true)
    setAddError(null)
    try {
      await onAdd({ pub: pubKey.trim(), label: label.trim(), gatewayUrl: gatewayUrl.trim() })
      setPubKey('')
      setLabel('')
      setGatewayUrl('')
    } catch (err) {
      setAddError(err instanceof ApiError ? err.message : 'Could not add feed.')
    } finally {
      setAdding(false)
    }
  }

  const remove = async (key) => {
    setRemoving(key)
    try {
      await onRemove(key)
    } finally {
      setRemoving(null)
    }
  }

  return (
    <div className="grid lg:grid-cols-3 gap-6">
      <div className="lg:col-span-2">
        {loading && (
          <div className="flex items-center gap-2 text-sm text-ink-400 py-6">
            <Loader2 size={16} className="animate-spin" /> Loading feeds…
          </div>
        )}
        {error && !loading && (
          <div className="mb-4 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200" role="alert">
            <AlertTriangle size={14} className="mt-0.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        {!loading && follows.length === 0 && !error && (
          <Card className="p-8 text-center" data-testid="follows-empty">
            <Users size={20} className="mx-auto text-kerf-300" aria-hidden="true" />
            <h3 className="mt-3 font-display text-lg font-semibold tracking-tight">
              A workshop is the set of feeds you follow
            </h3>
            <p className="mt-1 text-sm text-ink-400">
              Add a publisher&apos;s key and gateway to start browsing their feed.
              This is entirely local — it changes nothing on their end.
            </p>
          </Card>
        )}
        {!loading && follows.length > 0 && (
          <ul className="flex flex-col gap-2" data-testid="follows-list">
            {follows.map((f) => (
              <li key={f.pub}>
                <Card className="flex items-center gap-3 px-4 py-3">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2 min-w-0">
                      <span className="text-sm font-medium text-ink-100 truncate">
                        {f.label || truncatePub(f.pub)}
                      </span>
                    </div>
                    <p className="mt-0.5 text-[11px] font-mono text-ink-500 truncate" title={f.pub}>
                      {truncatePub(f.pub)}
                    </p>
                    {f.gateway_url && (
                      <p className="text-[11px] text-ink-500 truncate">{f.gateway_url}</p>
                    )}
                  </div>
                  <button
                    type="button"
                    onClick={() => remove(f.pub)}
                    disabled={removing === f.pub}
                    className="p-1.5 rounded text-red-300 hover:bg-red-500/10 disabled:opacity-40 shrink-0"
                    title={`Unfollow ${f.label || truncatePub(f.pub)}`}
                  >
                    {removing === f.pub
                      ? <Loader2 size={14} className="animate-spin" />
                      : <Trash2 size={14} />}
                  </button>
                </Card>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div>
        <Card className="p-4">
          <h3 className="text-sm font-semibold text-ink-100 mb-3">Add feed</h3>
          <form onSubmit={submit} className="flex flex-col gap-3">
            <Input
              label="Publisher key"
              placeholder="ed25519:…"
              value={pubKey}
              onChange={(e) => setPubKey(e.target.value)}
            />
            <Input
              label="Label (optional)"
              placeholder="e.g. Kerf default feed"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
            <Input
              label="Gateway URL"
              placeholder="https://kerf.sh"
              value={gatewayUrl}
              onChange={(e) => setGatewayUrl(e.target.value)}
              hint="Any gateway serving the DMTAP-PUB well-known routes works — kerf.sh is one gateway among equals."
            />
            {addError && <p className="text-xs text-red-300">{addError}</p>}
            <Button type="submit" variant="primary" size="sm" disabled={adding}>
              {adding
                ? <><Loader2 size={13} className="animate-spin" /> Adding…</>
                : <><Plus size={13} /> Add feed</>}
            </Button>
          </form>
        </Card>
      </div>
    </div>
  )
}

export function Workshop() {
  const [tab, setTab] = useState('browse') // 'browse' | 'feeds'
  const [items, setItems] = useState(null)
  const [follows, setFollows] = useState(null)
  const [error, setError] = useState(null)
  const [followsError, setFollowsError] = useState(null)
  const [loading, setLoading] = useState(true)
  const [pinBusy, setPinBusy] = useState({})

  const loadAll = useCallback(() => {
    setLoading(true)
    Promise.all([
      pub.listWorkshop().catch((err) => {
        setError(err instanceof ApiError ? err.message : 'Could not load the Workshop.')
        return []
      }),
      pub.listFollows().catch((err) => {
        setFollowsError(err instanceof ApiError ? err.message : 'Could not load feeds.')
        return []
      }),
    ]).then(([workshopItems, followsList]) => {
      setItems(Array.isArray(workshopItems) ? workshopItems : [])
      setFollows(Array.isArray(followsList) ? followsList : [])
    }).finally(() => setLoading(false))
  }, [])

  useEffect(() => { loadAll() }, [loadAll])

  const followsByPub = useMemo(() => {
    const m = new Map()
    for (const f of follows || []) m.set(f.pub, f)
    return m
  }, [follows])

  const supersededIds = useMemo(() => {
    const s = new Set()
    for (const it of items || []) {
      if (it.supersedes) s.add(it.supersedes)
    }
    return s
  }, [items])

  const onTogglePin = useCallback(async (item) => {
    setPinBusy((b) => ({ ...b, [item.announce_id]: true }))
    const wasPinned = !!item.pinned
    setItems((list) => list.map((i) => (
      i.announce_id === item.announce_id ? { ...i, pinned: !wasPinned } : i
    )))
    try {
      if (wasPinned) await pub.unpin(item.announce_id)
      else await pub.pin(item.announce_id)
    } catch (err) {
      // revert
      setItems((list) => list.map((i) => (
        i.announce_id === item.announce_id ? { ...i, pinned: wasPinned } : i
      )))
      setError(err instanceof ApiError ? err.message : 'Pin action failed.')
    } finally {
      setPinBusy((b) => {
        const n = { ...b }
        delete n[item.announce_id]
        return n
      })
    }
  }, [])

  const onAddFollow = useCallback(async ({ pub: pubKey, label, gatewayUrl }) => {
    await pub.addFollow({ pub: pubKey, label, gatewayUrl })
    loadAll()
  }, [loadAll])

  const onRemoveFollow = useCallback(async (pubKey) => {
    await pub.removeFollow(pubKey)
    loadAll()
  }, [loadAll])

  const list = items || []
  const followsList = follows || []

  return (
    <Layout>
      <div className="flex items-end justify-between flex-wrap gap-4 mb-4">
        <div>
          <p className="font-mono text-[11px] uppercase tracking-[0.2em] text-kerf-300">
            Distributed
          </p>
          <h1 className="mt-2 font-display text-3xl sm:text-4xl font-semibold tracking-tight">
            Workshop
          </h1>
          <p className="mt-1 text-sm text-ink-400 max-w-xl">
            Browse and publish parts, assemblies, PCBs, and drawings over{' '}
            <a
              href="https://github.com/vul-os/dmtap"
              target="_blank"
              rel="noreferrer"
              className="text-kerf-300 hover:underline"
            >
              DMTAP-PUB
            </a>
            . There&apos;s no central server — this view is built from the{' '}
            {followsList.length} feed{followsList.length === 1 ? '' : 's'} you follow.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg bg-ink-900 border border-ink-800 p-1">
          <button
            type="button"
            onClick={() => setTab('browse')}
            className={
              'h-8 px-3 rounded-md text-xs font-medium transition-colors ' +
              (tab === 'browse'
                ? 'bg-kerf-300 text-ink-950'
                : 'text-ink-200 hover:text-ink-100 hover:bg-ink-800')
            }
          >
            Browse
          </button>
          <button
            type="button"
            data-testid="workshop-tab-feeds"
            onClick={() => setTab('feeds')}
            className={
              'h-8 px-3 rounded-md text-xs font-medium transition-colors ' +
              (tab === 'feeds'
                ? 'bg-kerf-300 text-ink-950'
                : 'text-ink-200 hover:text-ink-100 hover:bg-ink-800')
            }
          >
            Feeds ({followsList.length})
          </button>
        </div>
      </div>

      {tab === 'browse' && (
        <>
          {error && (
            <div
              className="mb-6 flex items-start gap-2 rounded-lg border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-200"
              role="alert"
              data-testid="workshop-error-banner"
            >
              <AlertTriangle size={14} className="mt-0.5 shrink-0" aria-hidden="true" />
              <span>{error}</span>
            </div>
          )}

          {loading && items === null && (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {[0, 1, 2, 3].map((i) => (
                <Card key={i} className="p-4 animate-pulse">
                  <div className="h-4 w-3/4 rounded bg-ink-800" />
                  <div className="mt-3 h-3 w-1/2 rounded bg-ink-800/70" />
                  <div className="mt-4 h-3 w-1/3 rounded bg-ink-800/70" />
                </Card>
              ))}
            </div>
          )}

          {!loading && list.length === 0 && (
            <BrowseEmptyState hasFollows={followsList.length > 0} onGoToFeeds={() => setTab('feeds')} />
          )}

          {list.length > 0 && (
            <div className="grid sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-4">
              {list.map((item) => (
                <WorkshopCard
                  key={item.announce_id}
                  item={item}
                  publisherLabel={followsByPub.get(item.pub)?.label}
                  superseded={supersededIds.has(item.announce_id)}
                  onTogglePin={onTogglePin}
                  pinBusy={!!pinBusy[item.announce_id]}
                />
              ))}
            </div>
          )}

          <p className="mt-8 text-center text-xs text-ink-500">
            Want to browse the parts catalog instead?{' '}
            <Link to="/library" className="text-kerf-300 hover:underline">
              Open the Library
            </Link>
          </p>
        </>
      )}

      {tab === 'feeds' && (
        <FollowsPanel
          follows={followsList}
          loading={loading && follows === null}
          error={followsError}
          onAdd={onAddFollow}
          onRemove={onRemoveFollow}
        />
      )}
    </Layout>
  )
}

export default Workshop
