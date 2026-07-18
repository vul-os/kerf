// API helpers for the cloud-hosted-convenience surface (Workshop, Library,
// hosted git, operator email admin). Kerf has no billing anywhere.
//
// Mirrors the patterns in src/lib/api.js: same fetch wrapper for bearer auth
// and refresh-on-401, same ApiError shape. We intentionally re-import the
// `request` style logic via a thin wrapper exported alongside `api` instead
// of duplicating the refresh dance — but src/lib/api.js doesn't export
// `request` directly, so we replicate just enough here. If src/lib/api.js
// gains an exported request(), swap to that and delete the local copy.

import { useAuth } from '../store/auth.js'
import { ApiError } from '../lib/api.js'

const API_URL = import.meta.env.VITE_API_URL || ''

let refreshing = null

async function refreshAccessToken() {
  if (refreshing) return refreshing
  const { refreshToken, setSession, logout } = useAuth.getState()
  if (!refreshToken) throw new Error('no refresh token')

  refreshing = (async () => {
    const res = await fetch(`${API_URL}/auth/refresh`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ refresh_token: refreshToken }),
    })
    if (!res.ok) {
      logout()
      throw new Error('refresh failed')
    }
    const data = await res.json()
    setSession({
      accessToken: data.access_token,
      refreshToken: data.refresh_token,
      user: data.user,
    })
    return data.access_token
  })().finally(() => { refreshing = null })

  return refreshing
}

async function request(path, { method = 'GET', body, headers = {}, auth = true } = {}) {
  const url = path.startsWith('http') ? path : `${API_URL}${path}`
  const h = { 'content-type': 'application/json', ...headers }
  if (auth) {
    const token = useAuth.getState().accessToken
    if (token) h.authorization = `Bearer ${token}`
  }
  const send = () => fetch(url, {
    method,
    headers: h,
    body: body == null ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)),
  })

  let res = await send()
  if (res.status === 401 && auth && useAuth.getState().refreshToken) {
    try {
      const newToken = await refreshAccessToken()
      h.authorization = `Bearer ${newToken}`
      res = await send()
    } catch { /* fall through */ }
  }

  if (!res.ok) {
    const text = await res.text().catch(() => '')
    let msg = text
    try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
    throw new ApiError(res.status, msg || res.statusText)
  }
  if (res.status === 204) return null
  return res.json()
}

// ---- Pub (distributed Workshop, DMTAP-PUB) ----
// The Workshop is no longer a hosted listings service — it is a client-side
// view over feeds you follow, per decisions.md's 2026-07-17 "Final form"
// ADR and docs/distributed-workshop.md. All endpoints sit under /api/pub.
// This is a core MIT node capability (kerf-pub), never gated on
// `cloudEnabled`. Contract (frontend wave 2, coded against a parallel
// backend build):
//   GET  /api/pub/identity                 -> { pub: string|null }
//   POST /api/pub/identity                 -> { pub: string }
//   GET  /api/pub/follows                  -> [{ pub, label, gateway_url }]
//   POST /api/pub/follows { pub, label, gateway_url }
//   DELETE /api/pub/follows/:pub
//   GET  /api/pub/workshop -> [{ announce_id, pub, meta, roots, ts,
//     supersedes, availability: { status, holders, last_verified }, pinned }]
//   POST /api/pub/publish { project_id, metadata, children? } -> { announce_id }
//   GET  /api/pub/assembly-candidates/:project_id -> [{ announce_id, name, kind }]
//   GET  /api/pub/bom/:announce_id -> { announce_id, parts: [...], cycles: [...] }
//   POST/DELETE /api/pub/pin/:announce_id
//   POST /api/pub/pin/:announce_id/hydrate
export const pub = {
  // GET /api/pub/identity — the local node's Ed25519 publishing keypair,
  // or {pub: null} if one hasn't been created yet.
  getIdentity() {
    return request('/api/pub/identity')
  },

  // POST /api/pub/identity — creates the identity keypair the first time
  // this node publishes. Idempotent-ish from the UI's perspective: callers
  // should check getIdentity() first and only call this from the
  // "create your publishing identity" prompt.
  createIdentity() {
    return request('/api/pub/identity', { method: 'POST' })
  },

  // GET /api/pub/follows — the set of feeds that make up "your workshop".
  listFollows() {
    return request('/api/pub/follows')
  },

  // POST /api/pub/follows { pub, label, gateway_url } — follow a publisher.
  // Entirely local: no permission needed from the followed identity.
  addFollow({ pub: pubKey, label, gatewayUrl }) {
    return request('/api/pub/follows', {
      method: 'POST',
      body: { pub: pubKey, label: label || '', gateway_url: gatewayUrl || '' },
    })
  },

  // DELETE /api/pub/follows/:pub — unfollow. Local only, changes nothing
  // on the publisher's end.
  removeFollow(pubKey) {
    return request(`/api/pub/follows/${encodeURIComponent(pubKey)}`, { method: 'DELETE' })
  },

  // GET /api/pub/workshop — the derived, rebuildable browse index built by
  // crawling followed feeds. Never authoritative; the feeds themselves are.
  listWorkshop() {
    return request('/api/pub/workshop')
  },

  // POST /api/pub/publish { project_id, metadata, children? } -> { announce_id }.
  // Irrevocable once any other node holds a copy — the UI must confirm this
  // explicitly before calling. `metadata` is { name, description,
  // artifact_kind, license, units, tags }. `children` is only sent for
  // artifact_kind: "assembly" — an array of { ref_kind: "pin"|"track",
  // manifest_root?, announce_id?, quantity }; pin→manifest_root,
  // track→announce_id. The backend 400s naming any ref it can't resolve.
  publish({ projectId, metadata, children }) {
    const body = { project_id: projectId, metadata }
    if (children) body.children = children
    return request('/api/pub/publish', {
      method: 'POST',
      body,
    })
  },

  // GET /api/pub/assembly-candidates/:project_id -> [{ announce_id, name,
  // kind }] — the node owner's own published announces, for the assembly
  // "children" picker. v1 only lists announce_ids (usable for `track`
  // children); `pin` children need a manifest_root, which this endpoint
  // doesn't carry, so the UI collects those via free-text entry instead.
  assemblyCandidates(projectId) {
    return request(`/api/pub/assembly-candidates/${encodeURIComponent(projectId)}`)
  },

  // GET /api/pub/bom/:announce_id -> { announce_id,
  //   parts: [{ ref, ref_kind, resolved_announce, quantity_total }],
  //   cycles: [{ ref, ref_kind, path }] }
  // The §23.6.3 BOM walk from an assembly-kind announce. A non-empty
  // `cycles` means that subtree's BOM could not be fully computed — the UI
  // must surface it, not silently drop the affected parts.
  bom(announceId) {
    return request(`/api/pub/bom/${encodeURIComponent(announceId)}`)
  },

  // POST /api/pub/pin/:announce_id — fetch + durably keep + start serving.
  // Returns { pinned, hydrated, missing_chunks, error? }: `pinned` alone
  // does not mean the bytes are all local — check `hydrated`.
  pin(announceId) {
    return request(`/api/pub/pin/${encodeURIComponent(announceId)}`, { method: 'POST' })
  },

  // POST /api/pub/pin/:announce_id/hydrate — retry hydration of a pin that
  // came back incomplete (pinned: true, hydrated: false). Same request/
  // response shape as pin().
  hydratePin(announceId) {
    return request(`/api/pub/pin/${encodeURIComponent(announceId)}/hydrate`, { method: 'POST' })
  },

  // DELETE /api/pub/pin/:announce_id — stop serving locally. Never implies
  // deletion for other holders (there is no protocol-level takedown).
  unpin(announceId) {
    return request(`/api/pub/pin/${encodeURIComponent(announceId)}`, { method: 'DELETE' })
  },
}

// ---- Library ----
// Canonical home for the parts catalog. The Library is the discovery
// surface for individual Parts (M3 screws, 555 timers, etc.) — distinct
// from Workshop, which lists whole projects. Both endpoints share a SQL
// implementation in backend/cloud/workshop/handlers.go, but the Library
// route is the one new callers should use.
//
// Returned shape: { rows: [{ file_id, project_id, slug?, name,
//                            manufacturer?, mpn?, category?,
//                            primary_photo_url?, author }],
//                   limit, total }

export const library = {
  // GET /api/library/parts?search=&category=&verified_only=
  // All filters are optional; an empty payload returns the
  // verified-first, recently-updated head of the catalog (capped at 100).
  listParts({ search, category, verifiedOnly } = {}) {
    const q = new URLSearchParams()
    if (search) q.set('search', search)
    if (category) q.set('category', category)
    if (verifiedOnly) q.set('verified_only', 'true')
    const qs = q.toString()
    return request(`/api/library/parts${qs ? `?${qs}` : ''}`)
  },

  // GET /api/library/parts/:slug — single Part detail row. Phase 3 of the
  // Library split ships the route + frontend; the backend handler arrives
  // in Phase 4. Until then this 404s and the `/library/:slug` route
  // surfaces a "Part not found" empty state. The detail row is expected
  // to be a superset of the listParts() row shape: same fields plus the
  // parsed JSON `content` (description, datasheet_url, photos[],
  // distributors[]) and the source project's slug for "view in workshop".
  getPart(slug) {
    return request(`/api/library/parts/${encodeURIComponent(slug)}`)
  },

  // POST /api/library/submissions — manufacturer-PR submission flow
  // (Library Phase 3, ROADMAP row 73). Auth required (any role). The row
  // lands in library_part_submissions.status='pending' and surfaces on the
  // admin queue at /api/admin/library/submissions. `targetWorkspaceSlug`
  // names the curated Library workspace the contribution targets (e.g.
  // 'kerf-system'); `payload` is a Part-shape JSON object with at minimum
  // {name, manufacturer, mpn, category, description}. Returns {id} on 201.
  submitPart({ targetWorkspaceSlug, payload }) {
    return request('/api/library/submissions', {
      method: 'POST',
      body: {
        target_workspace_slug: targetWorkspaceSlug,
        payload,
      },
    })
  },

  /** POST /api/projects/:pid/files/:fid/derived — derived-artifacts cache lookup
   *  (ROADMAP row 67 Phase 2). Returns {cached, derivedKind, payload, error?}
   *  where payload is a Uint8Array on hit, null otherwise. A 501 response is
   *  the documented "compile-on-demand-not-yet-wired" miss and is mapped to
   *  {cached:false, ...} (NOT thrown) so callers can fall through. Other
   *  failures (network/auth/4xx) throw an ApiError. */
  async lookupDerivedArtifact({ projectId, fileId, derivedKind }) {
    let body
    try {
      body = await request(
        `/api/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/derived`,
        { method: 'POST', body: { derived_kind: derivedKind } },
      )
    } catch (err) {
      if (err instanceof ApiError && err.status === 501) {
        return { cached: false, derivedKind, payload: null, error: err.message }
      }
      throw err
    }
    const cached = !!(body && body.cached)
    const kind = (body && body.derived_kind) || derivedKind
    let payload = null
    if (cached && body && typeof body.payload_b64 === 'string' && body.payload_b64) {
      try {
        const bin = atob(body.payload_b64)
        const arr = new Uint8Array(bin.length)
        for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i)
        payload = arr
      } catch {
        return { cached: false, derivedKind: kind, payload: null, error: 'invalid base64' }
      }
    }
    return { cached: cached && payload != null, derivedKind: kind, payload }
  },

  /** POST /api/projects/:pid/files/:fid/derived/store — derived-artifacts
   *  cache populate (ROADMAP row 67 Phase 2, write-back half). Pairs with
   *  `lookupDerivedArtifact`: after a successful local recompile of a
   *  cross-project source, callers fire-and-forget this helper so the next
   *  consumer skips the recompile cost. `payload` is a Uint8Array (raw
   *  encoded artifact bytes); we base64-encode it inline. The backend caps
   *  decoded payloads at 16 MiB and returns {stored:true, derived_kind,
   *  payload_size_bytes} on 200; non-200s throw ApiError so the caller's
   *  fire-and-forget try/catch can swallow them. */
  async storeDerivedArtifact({ projectId, fileId, derivedKind, payload }) {
    if (!(payload instanceof Uint8Array)) {
      throw new TypeError('storeDerivedArtifact: payload must be a Uint8Array')
    }
    let payloadB64
    if (typeof Buffer !== 'undefined') {
      payloadB64 = Buffer.from(payload).toString('base64')
    } else {
      // Browser path: btoa over the byte string. Chunk to avoid blowing the
      // call stack on multi-MB payloads (apply()'s arg limit is ~64k on V8).
      let bin = ''
      const CHUNK = 0x8000
      for (let i = 0; i < payload.length; i += CHUNK) {
        bin += String.fromCharCode.apply(null, payload.subarray(i, i + CHUNK))
      }
      payloadB64 = btoa(bin)
    }
    const body = await request(
      `/api/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/derived/store`,
      { method: 'POST', body: { derived_kind: derivedKind, payload_b64: payloadB64 } },
    )
    return {
      stored: !!(body && body.stored),
      payloadSize: (body && Number(body.payload_size_bytes)) || 0,
    }
  },

  /** GET /api/projects/:pid/files/:fid/diff?against=<rev> — returns component count
   *  delta + BOM total delta vs a revision (or the immediately preceding one if
   *  the rev id is omitted). Used by the assembly editor's 'out of date' chip
   *  tooltip (ROADMAP row 68 Phase 3). Returns { componentsAdded, componentsRemoved,
   *  componentsDelta, bomTotalDeltaUsd, against } — re-cased from the snake_case
   *  backend payload. Throws ApiError on non-200. */
  async diffFile({ projectId, fileId, against }) {
    const qs = against ? `?against=${encodeURIComponent(against)}` : ''
    const body = await request(
      `/api/projects/${encodeURIComponent(projectId)}/files/${encodeURIComponent(fileId)}/diff${qs}`,
    )
    return {
      componentsAdded: (body && body.components_added) || 0,
      componentsRemoved: (body && body.components_removed) || 0,
      componentsDelta: (body && body.components_delta) || 0,
      bomTotalDeltaUsd: body && body.bom_total_delta_usd != null ? Number(body.bom_total_delta_usd) : null,
      against: (body && body.against) || null,
    }
  },
}

// ---- Admin: Library submissions queue ----
// Library Phase 3 (ROADMAP row 73). All routes require account_role='admin'
// or 'system' — the backend re-checks on every endpoint, the frontend just
// uses these helpers behind the AdminPublishers-style gate.
export const adminLibrary = {
  // GET /api/admin/library/submissions?status=pending&page=&page_size=
  // → { submissions: [...], page, page_size, has_more }
  listSubmissions: ({ status = 'pending', page = 1, pageSize } = {}) => {
    const q = new URLSearchParams()
    if (status) q.set('status', status)
    if (page) q.set('page', String(page))
    if (pageSize) q.set('page_size', String(pageSize))
    const qs = q.toString()
    return request(`/api/admin/library/submissions${qs ? `?${qs}` : ''}`)
  },

  // PUT /api/admin/library/submissions/:id { action, review_note }
  // action ∈ 'approve'|'reject'. On approve, the payload is copied as a new
  // kind='part' file in the target workspace's library project.
  reviewSubmission: (id, { action, reviewNote }) =>
    request(`/api/admin/library/submissions/${encodeURIComponent(id)}`, {
      method: 'PUT',
      body: { action, review_note: reviewNote || '' },
    }),
}

// ---- Git ----
// Local git only, per decisions.md's 2026-07-17 "local git only; no OAuth"
// addendum: a kerf project is a plain local git repo, and collaboration is
// git push/pull to any remote the user configures — a teammate's node, a
// homelab box, GitHub, Gitea. There is no hosted-git product, no kerf-run
// GitHub OAuth app, no server-held tokens. Authentication for a remote uses
// the caller's own SSH key or token, exactly like the git CLI; kerf never
// stores credentials. All endpoints sit under /api/git/:project_id.
export const git = {
  // GET /api/git/:pid/status
  // -> { initialized, branch, dirty, ahead, behind, remotes: [{name,url}] }
  status: (projectId) =>
    request(`/api/git/${encodeURIComponent(projectId)}/status`),

  // POST /api/git/:pid/init — create an empty local repo for the project.
  init: (projectId) =>
    request(`/api/git/${encodeURIComponent(projectId)}/init`, { method: 'POST' }),

  // POST /api/git/:pid/commit { message } -> { sha }. Stages + commits
  // everything in the working tree.
  commit: (projectId, message) =>
    request(`/api/git/${encodeURIComponent(projectId)}/commit`, {
      method: 'POST',
      body: { message },
    }),

  // GET /api/git/:pid/log?limit=50 -> [{ sha, message, author, ts }]
  log: (projectId, limit = 50) => {
    const q = new URLSearchParams()
    if (limit) q.set('limit', String(limit))
    return request(`/api/git/${encodeURIComponent(projectId)}/log?${q.toString()}`)
  },

  // GET /api/git/:pid/remotes -> [{ name, url }]
  listRemotes: (projectId) =>
    request(`/api/git/${encodeURIComponent(projectId)}/remotes`),

  // POST /api/git/:pid/remotes { name, url } — add (or update) a remote.
  addRemote: (projectId, name, url) =>
    request(`/api/git/${encodeURIComponent(projectId)}/remotes`, {
      method: 'POST',
      body: { name, url },
    }),

  // DELETE /api/git/:pid/remotes/:name
  removeRemote: (projectId, name) =>
    request(`/api/git/${encodeURIComponent(projectId)}/remotes/${encodeURIComponent(name)}`, {
      method: 'DELETE',
    }),

  // POST /api/git/:pid/push { remote, branch }
  push: (projectId, remote, branch) =>
    request(`/api/git/${encodeURIComponent(projectId)}/push`, {
      method: 'POST',
      body: { remote, branch },
    }),

  // POST /api/git/:pid/pull { remote, branch }
  pull: (projectId, remote, branch) =>
    request(`/api/git/${encodeURIComponent(projectId)}/pull`, {
      method: 'POST',
      body: { remote, branch },
    }),
}

// ---- Admin: transactional email ----
// Mirrors the shape of api.admin.* in src/lib/api.js but lives here
// because the backend endpoints are cloud-only (built behind the
// `cloud` Go build tag). All routes require account_role='admin'.
export const adminEmail = {
  // GET /api/admin/email/providers
  // → { providers: [{provider, enabled, has_secret, rate_limit_per_minute,
  //                  last_used_at?, updated_at, active}], active }
  listProviders: () => request('/api/admin/email/providers'),

  // PUT /api/admin/email/providers/:provider
  // body: { enabled, rate_limit_per_minute, secret: { api_key?, from_email,
  //          from_name?, region?, smtp_host?, smtp_port?, smtp_username?,
  //          smtp_password? } }
  upsertProvider: (provider, payload) =>
    request(`/api/admin/email/providers/${encodeURIComponent(provider)}`, {
      method: 'PUT',
      body: payload,
    }),

  // DELETE /api/admin/email/providers/:provider — idempotent.
  deleteProvider: (provider) =>
    request(`/api/admin/email/providers/${encodeURIComponent(provider)}`, {
      method: 'DELETE',
    }),

  // POST /api/admin/email/test  { to, template, vars? }
  // Renders + enqueues a single send. Returns { status: "queued" }.
  testSend: ({ to, template, vars }) =>
    request('/api/admin/email/test', {
      method: 'POST',
      body: { to, template, vars: vars || {} },
    }),

  // GET /api/admin/email/log?limit=50&before=<iso>
  // → { entries: [{id, user_id?, template, to_email, provider?, status,
  //                error?, sent_at?, created_at}] }
  log: ({ limit = 50, before } = {}) => {
    const q = new URLSearchParams()
    if (limit) q.set('limit', String(limit))
    if (before) q.set('before', before)
    return request(`/api/admin/email/log?${q.toString()}`)
  },
}
