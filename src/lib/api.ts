import { useAuth } from '../store/auth.js'
import { toast } from '../components/ToastBus.jsx'
import { streamSse } from './sseClient.js'
import type {
  ApiUser,
  AuthSession,
  ApiWorkspace,
  WorkspaceMember,
  ApiProject,
  ApiFile,
  ApiThread,
  ApiChatMessage,
  ProjectMember,
  ShareLink,
  ShareInfo,
  FileRevision,
  RevisionsSize,
  PurgeRevisionsResult,
  ActivityPage,
  BOMResult,
  UploadInitResponse,
  ApiToken,
  AdminDistributor,
  AdminPublishersPage,
  AdminPublisher,
  ImportResult,
  CompileIfcResult,
  TopoRunResult,
  WirevizResult,
  PlcLintResult,
  PrintSliceResult,
  JewelryCostResult,
  ClashDetectResult,
  BuildingEnergyResult,
  PvShadingResult,
  ToolCallResult,
} from '../types/api.js'

const API_URL = import.meta.env.VITE_API_URL || ''

// Single in-flight refresh promise to coalesce concurrent 401s.
let refreshing: Promise<string> | null = null

async function refreshAccessToken(): Promise<string> {
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

// Default fetch timeout. Chosen so a stuck backend (LLM provider hang,
// hung database query, dead worker) surfaces as a visible error in the
// chat UI within ~60 s rather than spinning forever on "Kerf is thinking…".
// Individual call sites can override with a longer or shorter ms value;
// pass timeoutMs: 0 to disable.
export const DEFAULT_TIMEOUT_MS = 60_000
// Chat sendMessage may legitimately take longer when the assistant uses
// several tool calls or a slow provider. 3 minutes is generous; users
// will see a clear "request timed out" error rather than an indefinite spinner.
export const CHAT_TIMEOUT_MS = 180_000

async function fetchWithTimeout(url: string, init: RequestInit, timeoutMs: number | undefined): Promise<Response> {
  if (!timeoutMs || timeoutMs <= 0) return fetch(url, init)
  const ctrl = new AbortController()
  const t = setTimeout(() => ctrl.abort(), timeoutMs)
  try {
    return await fetch(url, { ...init, signal: ctrl.signal })
  } finally {
    clearTimeout(t)
  }
}

interface RequestOptions {
  method?: string
  body?: unknown
  headers?: Record<string, string>
  auth?: boolean
  raw?: boolean
  timeoutMs?: number
}

// request() — thin fetch wrapper shared by every api.* method below.
//
// Overloaded so `{ raw: true }` callers (fetchRaw) get back the raw Response,
// while everyone else gets the parsed-JSON type they asked for via <T>.
function request(path: string, opts: RequestOptions & { raw: true }): Promise<Response>
function request<T = unknown>(path: string, opts?: RequestOptions): Promise<T>
async function request<T = unknown>(
  path: string,
  { method = 'GET', body, headers = {}, auth = true, raw = false, timeoutMs = DEFAULT_TIMEOUT_MS }: RequestOptions = {},
): Promise<T | Response> {
  const url = path.startsWith('http') ? path : `${API_URL}${path}`
  const h: Record<string, string> = { 'content-type': 'application/json', ...headers }
  if (auth) {
    const token = useAuth.getState().accessToken
    if (token) h.authorization = `Bearer ${token}`
  }
  const init: RequestInit = {
    method,
    headers: h,
    body: body == null ? undefined : (typeof body === 'string' ? body : JSON.stringify(body)),
  }
  let res: Response
  try {
    res = await fetchWithTimeout(url, init, timeoutMs)
  } catch (e: unknown) {
    if (e instanceof Error && e.name === 'AbortError') {
      throw new ApiError(0, `Request timed out after ${Math.round((timeoutMs ?? 0) / 1000)}s. Please try again.`)
    }
    // Network errors (DNS, offline, CORS preflight, etc.) reach here as
    // generic TypeError. Surface them as ApiError so call sites can
    // uniformly catch + render instead of swallowing.
    const message = e instanceof Error ? e.message : undefined
    throw new ApiError(0, message || 'Network error — check your connection.')
  }

  if (res.status === 401 && auth && useAuth.getState().refreshToken) {
    try {
      const newToken = await refreshAccessToken()
      h.authorization = `Bearer ${newToken}`
      res = await fetchWithTimeout(url, init, timeoutMs)
    } catch {
      // fall through to error below
    }
  }

  if (raw) return res

  if (res.status === 429) {
    const text = await res.text()
    let retryAfter: number | null = null
    try {
      const body = JSON.parse(text)
      retryAfter = body.retry_after ?? null
    } catch { /* ignore */ }
    const msg = retryAfter != null
      ? `Too many requests — try again in ${retryAfter} seconds`
      : 'Too many requests — please slow down'
    toast.error(msg)
    throw new ApiError(429, 'rate limit exceeded')
  }

  if (!res.ok) {
    const text = await res.text()
    let msg = text
    try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
    throw new ApiError(res.status, msg || res.statusText)
  }
  if (res.status === 204) return null as T
  return res.json()
}

export class ApiError extends Error {
  status: number
  /** Set by readErrorJSON() when the server's error body carries a machine-readable `code`. */
  code?: string
  constructor(status: number, message: string) { super(message); this.status = status }
}

// ---------------------------------------------------------------------------
// Gaps in src/types/api.ts found while migrating this file (T-505): the
// shared type doesn't model these two shapes, and this slice does not own
// src/types/ — see the T-505 report rather than editing it here.
// ---------------------------------------------------------------------------

/**
 * ApiWorkspace (src/types/api.ts) has no `avatar_url` field, but
 * src/routes/WorkspaceSettings.jsx reads/falls back on `ws.avatar_url` after
 * uploadWorkspaceAvatar/deleteWorkspaceAvatar. Extending locally rather than
 * widening the shared type (T-501's call).
 */
interface ApiWorkspaceWithAvatar extends ApiWorkspace {
  avatar_url?: string | null
}

/**
 * inviteWorkspaceMember's response isn't modeled in src/types/api.ts.
 * src/routes/WorkspaceMembers.jsx branches on `resp.added` (existing user,
 * added immediately) vs `resp.invite.token` (no account yet — show a
 * signup-invite link).
 */
interface InviteWorkspaceMemberResult {
  added?: boolean
  invite?: { token: string }
}

/**
 * ApiFile (src/types/api.ts) has no `mesh_url` field, but
 * src/store/workspace.ts reads `file.mesh_url` off both api.getFile's result
 * (loadFileForEditor) and a second internal getFile call in
 * loadComponentParts — the server-tessellated .glb URL for STEP files
 * (Performance Phase 3). src/store/workspace.ts's own `WorkspaceFile`
 * already extends `ApiFile` with an optional `mesh_url`; this mirrors that
 * same extension at the api.ts boundary rather than widening the shared
 * type (T-501's call).
 */
interface ApiFileWithMesh extends ApiFile {
  mesh_url?: string | null
}

/**
 * ApiThread (src/types/api.ts) has no `is_starred` field, but
 * src/store/workspace.ts's toggleStar action PATCHes `{ is_starred }`.
 * (workspace.ts's own `WorkspaceThread` already extends `ApiThread` with
 * this same field for its store-side type — mirrored here for the same
 * reason as ApiFileWithMesh above.)
 */
interface ApiThreadPatch extends Partial<ApiThread> {
  is_starred?: boolean
}

/**
 * sendMessage's real response is NOT a single ApiChatMessage — it is a
 * composite of the three rows one chat turn produces. src/types/api.ts's
 * `ApiChatMessage` lives under the "Threads / chat" section as if it also
 * covered sendMessage, but src/store/workspace.ts's sendMessage action
 * destructures `res.user_message` / `res.tool_messages` / `res.assistant_message`
 * — three separate messages, not one. Real T-501 finding: reported (see the
 * T-505 report), not edited into the shared type from this slice.
 */
export interface SendMessageResult {
  user_message: ChatMessage
  tool_messages: Array<ChatMessage & { tool_name?: string }>
  assistant_message: ChatMessage & { tool_calls?: Array<{ name: string; [key: string]: unknown }> }
}

/**
 * ApiChatMessage.part_refs is deliberately `unknown[]` in src/types/api.ts —
 * that file's own header flags it as having no direct evidence of a
 * stricter shape. src/store/workspace.ts's `WorkspaceMessage` needs the
 * stricter local `PartRef[]` and validates it itself; `any[]` bridges the
 * two independently-typed layers at this boundary rather than redeclaring
 * either type (`any` is a documented boundary tool per
 * docs/typescript-migration.md's conventions).
 */
type ChatMessage = Omit<ApiChatMessage, 'part_refs'> & { part_refs?: any[] }

/**
 * streamMessage()'s per-event `data` payload shape genuinely varies by
 * `event` name (assistant_text_delta vs tool_use_start vs assistant_done,
 * ...) — a discriminated union keyed by `event` would be the fully-typed
 * version of this but is out of this slice's scope (T-501 owns
 * `ChatStreamEvent`, and modeled `data` as `Record<string, unknown>` there,
 * which is honest about "no fixed shape" but still blocks
 * src/store/workspace.ts's sendMessageStreaming, which already switches on
 * `event` and reads whichever fields that event carries). `any` is the
 * pragmatic boundary type here — see docs/typescript-migration.md's
 * conventions on `any` as a boundary tool.
 */
export interface StreamMessageEvent {
  event: string
  data: any
}

/**
 * The chunked-upload finalize response is the created File row (id, name,
 * kind, parent_id, ...) PLUS the blob-storage fields — richer than
 * src/types/api.ts's `UploadFinalizeResult`, which lacks `name` even though
 * src/store/workspace.ts's uploadAsset/replacePartModel actions both treat
 * the result as a full file row (spreading it into the file list, reading
 * `.name`/`.id`) as well as reading `.storage_key`/`.mime_type` directly.
 * api.js's own uploadPartModel comment claims the narrower
 * `{storage_key, mime_type}` shape; the actual consumer needs both. Real
 * T-501 finding: reported, not edited into the shared type from this slice.
 */
export interface ChunkedUploadResult extends ApiFile {
  storage_key: string
  mime_type?: string
}

interface CreateFileBody {
  name: string
  kind?: string
  parent_id?: string | null
  content?: string
}

interface SendMessageBody {
  content: string
  part_refs?: unknown[]
  model?: string
}

export const api = {
  // ---- Auth ----
  register: (email: string, password: string, name: string) =>
    request<AuthSession>('/auth/register', { method: 'POST', body: { email, password, name }, auth: false }),
  login: (email: string, password: string) =>
    request<AuthSession>('/auth/login', { method: 'POST', body: { email, password }, auth: false }),
  forgotPassword: (email: string) =>
    request<void>('/auth/forgot-password', { method: 'POST', body: { email }, auth: false }),
  resetPassword: (token: string, password: string) =>
    request<AuthSession>('/auth/reset-password', { method: 'POST', body: { token, password }, auth: false }),
  requestVerification: () =>
    request<void>('/auth/request-verification', { method: 'POST', body: {} }),
  googleAuthUrl: () => `${API_URL}/auth/google/start`,
  githubAuthUrl: () => `${API_URL}/auth/github/login/start`,
  refresh: () => refreshAccessToken(),
  me: () => request<ApiUser>('/api/me'),
  updateMe: (patch: Partial<ApiUser>) => request<ApiUser>('/api/me', { method: 'PATCH', body: patch }),
  changePassword: (current_password: string, new_password: string) =>
    request<void>('/api/me/password', { method: 'POST', body: { current_password, new_password } }),
  deleteMe: () => request<void>('/api/me?confirm=DELETE', { method: 'DELETE' }),
  logout: () => {
    const { refreshToken, logout } = useAuth.getState()
    logout()
    if (refreshToken) {
      return request('/auth/logout', { method: 'POST', body: { refresh_token: refreshToken }, auth: false }).catch(() => {})
    }
  },

  // ---- Workspaces ----
  // src/store/workspaces.ts's loadAll defensively accepts either a bare
  // array OR a `{ workspaces: [...] }` wrapper (`Array.isArray(list) ? list
  // : list?.workspaces || []`) — real finding: api.js's own comment gives no
  // evidence either way, and this union is honest about that rather than
  // asserting the bare-array shape workspaces.ts's fallback implies might
  // not always hold. Reported in the T-505 report, not resolved here.
  listWorkspaces: () => request<ApiWorkspace[] | { workspaces: ApiWorkspace[] }>('/api/workspaces'),
  getWorkspace: (slug: string) => request<ApiWorkspace>(`/api/workspaces/${encodeURIComponent(slug)}`),
  createWorkspace: (body: Partial<ApiWorkspace>) => request<ApiWorkspace>('/api/workspaces', { method: 'POST', body }),
  updateWorkspace: (slug: string, patch: Partial<ApiWorkspace>) =>
    request<ApiWorkspace>(`/api/workspaces/${encodeURIComponent(slug)}`, { method: 'PATCH', body: patch }),
  deleteWorkspace: (slug: string) =>
    request<void>(`/api/workspaces/${encodeURIComponent(slug)}`, { method: 'DELETE' }),
  inviteWorkspaceMember: (slug: string, email: string, role: string) =>
    request<InviteWorkspaceMemberResult>(`/api/workspaces/${encodeURIComponent(slug)}/members`, { method: 'POST', body: { email, role } }),
  removeWorkspaceMember: (slug: string, userId: string) =>
    request<void>(`/api/workspaces/${encodeURIComponent(slug)}/members/${encodeURIComponent(userId)}`, { method: 'DELETE' }),
  changeWorkspaceMemberRole: (slug: string, userId: string, role: string) =>
    request<WorkspaceMember>(`/api/workspaces/${encodeURIComponent(slug)}/members/${encodeURIComponent(userId)}`, { method: 'PATCH', body: { role } }),
  uploadWorkspaceAvatar: async (slug: string, blob: Blob & { name?: string }): Promise<ApiWorkspaceWithAvatar> => {
    const fd = new FormData()
    const name = (blob && blob.name) || 'avatar.png'
    fd.append('file', blob, name)
    const url = `${API_URL}/api/workspaces/${encodeURIComponent(slug)}/avatar`
    const token = useAuth.getState().accessToken
    const headers: Record<string, string> = {}
    if (token) headers.authorization = `Bearer ${token}`
    let res = await fetch(url, { method: 'POST', headers, body: fd })
    if (res.status === 401 && useAuth.getState().refreshToken) {
      try {
        const newToken = await refreshAccessToken()
        headers.authorization = `Bearer ${newToken}`
        res = await fetch(url, { method: 'POST', headers, body: fd })
      } catch { /* fall through */ }
    }
    if (!res.ok) {
      const text = await res.text()
      let msg = text
      try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
      throw new ApiError(res.status, msg || res.statusText)
    }
    return res.json()
  },
  deleteWorkspaceAvatar: (slug: string) =>
    request<ApiWorkspaceWithAvatar>(`/api/workspaces/${encodeURIComponent(slug)}/avatar`, { method: 'DELETE' }),

  // ---- Projects ----
  // listProjects(workspaceId, { tag })
  // - workspaceId: optional. When set, scopes the listing to that workspace.
  // - tag: optional string or string[] of tag filters; multiple tags are
  //   ANDed server-side (every tag must be present on the row).
  listProjects: (workspaceId?: string | null, opts: { tag?: string | string[] } = {}) => {
    const q = new URLSearchParams()
    if (workspaceId) q.set('workspace_id', workspaceId)
    const tags = Array.isArray(opts.tag) ? opts.tag : (opts.tag ? [opts.tag] : [])
    for (const t of tags) {
      if (t) q.append('tag', t)
    }
    const qs = q.toString()
    return request<ApiProject[]>(`/api/projects${qs ? `?${qs}` : ''}`)
  },
  // createProject — body is `{ workspace_id, name, description, tags?, starter? }`.
  // - tags: array of free-form strings; the backend trims+dedupes.
  // - starter: "jscad" | "circuit" | "blank"; defaults to "jscad" server-side.
  // Old (name, description) positional shape is still accepted for
  // back-compat — the workspace store fills workspace_id when it's missing.
  createProject: (nameOrBody: string | Partial<ApiProject>, description?: string) => {
    if (nameOrBody && typeof nameOrBody === 'object') {
      return request<ApiProject>('/api/projects', { method: 'POST', body: nameOrBody })
    }
    const body = { name: nameOrBody, description }
    return request<ApiProject>('/api/projects', { method: 'POST', body })
  },
  getProject: (id: string) => request<ApiProject>(`/api/projects/${id}`),
  updateProject: (id: string, patch: Partial<ApiProject>) =>
    request<ApiProject>(`/api/projects/${id}`, { method: 'PATCH', body: patch }),
  deleteProject: (id: string) =>
    request<void>(`/api/projects/${id}`, { method: 'DELETE' }),

  // Upload a JPEG thumbnail rendered client-side. Multipart, so we
  // bypass the JSON request() helper.
  uploadProjectThumbnail: async (projectId: string, blob: Blob): Promise<ApiProject> => {
    const fd = new FormData()
    fd.append('file', blob, 'thumbnail.jpg')
    const url = `${API_URL}/api/projects/${projectId}/thumbnail`
    const token = useAuth.getState().accessToken
    const headers: Record<string, string> = {}
    if (token) headers.authorization = `Bearer ${token}`
    let res = await fetch(url, { method: 'POST', headers, body: fd })
    if (res.status === 401 && useAuth.getState().refreshToken) {
      try {
        const newToken = await refreshAccessToken()
        headers.authorization = `Bearer ${newToken}`
        res = await fetch(url, { method: 'POST', headers, body: fd })
      } catch { /* fall through */ }
    }
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new ApiError(res.status, text || res.statusText)
    }
    return res.json()
  },

  // Workshop gallery is files-in-repo now (image files under a project
  // `workshop/` folder); the old DB-gallery endpoints were retired.

  // ---- Files / Assemblies ----
  listFiles: (projectId: string) => request<ApiFileWithMesh[]>(`/api/projects/${projectId}/files`),
  createFile: (projectId: string, { name, kind = 'file', parent_id = null, content = '' }: CreateFileBody) =>
    request<ApiFileWithMesh>(`/api/projects/${projectId}/files`, { method: 'POST', body: { name, kind, parent_id, content } }),
  getFile: (projectId: string, fileId: string) => request<ApiFileWithMesh>(`/api/projects/${projectId}/files/${fileId}`),
  updateFile: (projectId: string, fileId: string, patch: Partial<ApiFile>) =>
    request<ApiFileWithMesh>(`/api/projects/${projectId}/files/${fileId}`, { method: 'PATCH', body: patch }),
  deleteFile: (projectId: string, fileId: string) =>
    request<void>(`/api/projects/${projectId}/files/${fileId}`, { method: 'DELETE' }),

  // fetchRaw — returns the raw Response (not parsed JSON). Used by the
  // component-substitution path to fetch STEP blob bytes.
  fetchRaw: (path: string, init: RequestOptions = {}) => request(path, { ...init, raw: true }),

  // Upload a binary asset (e.g. STEP file). The backend should return a File row.
  // We use multipart/form-data; do NOT set content-type — the browser will set
  // the correct boundary header automatically.
  uploadAsset: async (
    projectId: string,
    file: File,
    { kind = 'step', parent_id = null }: { kind?: string; parent_id?: string | null } = {},
  ): Promise<ApiFile> => {
    const fd = new FormData()
    fd.append('file', file)
    fd.append('name', file.name)
    fd.append('kind', kind)
    if (parent_id) fd.append('parent_id', parent_id)
    const url = `${API_URL}/api/projects/${projectId}/assets`
    const token = useAuth.getState().accessToken
    const headers: Record<string, string> = {}
    if (token) headers.authorization = `Bearer ${token}`
    let res = await fetch(url, { method: 'POST', headers, body: fd })
    if (res.status === 401 && useAuth.getState().refreshToken) {
      try {
        const newToken = await refreshAccessToken()
        headers.authorization = `Bearer ${newToken}`
        res = await fetch(url, { method: 'POST', headers, body: fd })
      } catch { /* fall through */ }
    }
    if (!res.ok) {
      const text = await res.text()
      let msg = text
      try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
      throw new ApiError(res.status, msg || res.statusText)
    }
    return res.json()
  },

  // Download a binary file. Returns an ArrayBuffer; uses bearer auth.
  downloadFileURL: async (projectId: string, fileId: string): Promise<ArrayBuffer> => {
    const url = `${API_URL}/api/projects/${projectId}/files/${fileId}/download`
    const token = useAuth.getState().accessToken
    const headers: Record<string, string> = {}
    if (token) headers.authorization = `Bearer ${token}`
    let res = await fetch(url, { headers })
    if (res.status === 401 && useAuth.getState().refreshToken) {
      try {
        const newToken = await refreshAccessToken()
        headers.authorization = `Bearer ${newToken}`
        res = await fetch(url, { headers })
      } catch { /* fall through */ }
    }
    if (!res.ok) {
      const text = await res.text().catch(() => '')
      throw new ApiError(res.status, text || res.statusText)
    }
    return res.arrayBuffer()
  },

  // ---- Chat ----
  listMessages: (projectId: string, threadId: string) =>
    request<ChatMessage[]>(`/api/projects/${projectId}/threads/${threadId}/messages`),
  sendMessage: (projectId: string, threadId: string, { content, part_refs, model }: SendMessageBody) =>
    request<SendMessageResult>(`/api/projects/${projectId}/threads/${threadId}/messages`, {
      method: 'POST',
      body: { content, part_refs, model },
      // Chat can legitimately take 30-90s with tool calls; allow up to 3 min
      // before surfacing a timeout so the UI never hangs indefinitely.
      timeoutMs: CHAT_TIMEOUT_MS,
    }),

  /**
   * Open an SSE stream for one chat turn.
   *
   * Returns an AsyncIterable<{ event: string, data: object }>.
   * The caller owns the AbortController; call abortController.abort() to cancel.
   */
  streamMessage(
    projectId: string,
    threadId: string,
    { content, part_refs, model }: SendMessageBody,
    abortSignal?: AbortSignal,
  ): AsyncIterable<StreamMessageEvent> {
    const url = `${API_URL}/api/projects/${projectId}/threads/${threadId}/messages/stream`
    const token = useAuth.getState().accessToken
    const headers = token ? { authorization: `Bearer ${token}` } : {}
    return streamSse(url, { content, part_refs, model }, { signal: abortSignal, headers })
  },

  // ---- Threads ----
  listThreads: (projectId: string, fileId?: string) => {
    const q = fileId ? `?file_id=${fileId}` : ''
    return request<ApiThread[]>(`/api/projects/${projectId}/threads${q}`)
  },
  createThread: (projectId: string, { title, file_id, model }: Partial<ApiThread> = {}) =>
    request<ApiThread>(`/api/projects/${projectId}/threads`, {
      method: 'POST',
      body: { title, file_id, model },
    }),
  updateThread: (projectId: string, threadId: string, patch: ApiThreadPatch) =>
    request<ApiThread>(`/api/projects/${projectId}/threads/${threadId}`, {
      method: 'PATCH',
      body: patch,
    }),
  deleteThread: (projectId: string, threadId: string) =>
    request<void>(`/api/projects/${projectId}/threads/${threadId}`, { method: 'DELETE' }),

  // ---- Members ----
  listMembers: (projectId: string) => request<ProjectMember[]>(`/api/projects/${projectId}/members`),
  inviteMember: (projectId: string, { email, role }: { email: string; role: string }) =>
    request<ProjectMember>(`/api/projects/${projectId}/members`, {
      method: 'POST',
      body: { email, role },
    }),
  updateMember: (projectId: string, userId: string, { role }: { role: string }) =>
    request<ProjectMember>(`/api/projects/${projectId}/members/${userId}`, {
      method: 'PATCH',
      body: { role },
    }),
  removeMember: (projectId: string, userId: string) =>
    request<void>(`/api/projects/${projectId}/members/${userId}`, { method: 'DELETE' }),

  // ---- Share Links ----
  listShareLinks: (projectId: string) => request<ShareLink[]>(`/api/projects/${projectId}/share/links`),
  createShareLink: (projectId: string, { role, expires_at, max_uses }: Partial<ShareLink> = {}) =>
    request<ShareLink>(`/api/projects/${projectId}/share/links`, {
      method: 'POST',
      body: { role, expires_at, max_uses },
    }),
  revokeShareLink: (projectId: string, linkId: string) =>
    request<void>(`/api/projects/${projectId}/share/links/${linkId}`, { method: 'DELETE' }),
  getShareInfo: (token: string) =>
    request<ShareInfo>(`/api/share/${token}`, { auth: false }),
  acceptShareLink: (token: string) =>
    request<void>(`/api/share/${token}/accept`, { method: 'POST' }),
  addShareComment: (token: string, customerName: string, body: string) =>
    request<void>(`/api/share/${token}/comments`, { method: 'POST', body: { customer_name: customerName, body }, auth: false }),
  recordShareApproval: (token: string, customerName: string, signature: string) =>
    request<void>(`/api/share/${token}/approve`, { method: 'POST', body: { customer_name: customerName, signature }, auth: false }),

  // ---- Models ----
  listModels: () => request<unknown[]>('/api/models'),

  // Chunked, resumable binary upload (Phase 2). Used for STEP files; see
  // ROADMAP.md "Performance roadmap". Computes a SHA-256 of the file, asks the backend for a
  // session (which may resume an existing one), uploads any missing chunks
  // with bounded concurrency + per-chunk retry, then finalizes.
  //
  // onProgress({received, total, bytes}) fires after each chunk completes.
  uploadAssetChunked: (projectId: string, file: File, opts: UploadAssetChunkedOpts = {}) =>
    uploadAssetChunked(projectId, file, opts),
  cancelUpload: (projectId: string, uploadId: string) => cancelUpload(projectId, uploadId),

  // ---- Bill of Materials ----
  getBOM: (projectId: string) => request<BOMResult>(`/api/projects/${projectId}/bom`),

  // ---- Activity timeline ----
  // Per-project merged feed of recent events (file revisions, chat messages,
  // file lifecycle, project_created). `before` is an ISO timestamp returned
  // as `next_cursor` by the previous page; pass it to walk further back.
  getActivity: (projectId: string, before?: string | null, limit?: number) =>
    request<ActivityPage>(`/api/projects/${projectId}/activity?limit=${limit ?? 50}${before ? `&before=${encodeURIComponent(before)}` : ''}`),

  // ---- Library: Part photos ----
  // Multipart upload of a single image. Backend resizes (longest side ≤
  // 1024 px), stores as JPEG, and appends to the Part's photos array. The
  // first photo on a Part is auto-promoted to primary.
  uploadPartPhoto: async (projectId: string, fileId: string, blob: Blob & { name?: string }): Promise<ApiFileWithMesh> => {
    const fd = new FormData()
    const name = (blob && blob.name) || 'photo.jpg'
    fd.append('file', blob, name)
    const url = `${API_URL}/api/projects/${projectId}/files/${fileId}/photos`
    const token = useAuth.getState().accessToken
    const headers: Record<string, string> = {}
    if (token) headers.authorization = `Bearer ${token}`
    let res = await fetch(url, { method: 'POST', headers, body: fd })
    if (res.status === 401 && useAuth.getState().refreshToken) {
      try {
        const newToken = await refreshAccessToken()
        headers.authorization = `Bearer ${newToken}`
        res = await fetch(url, { method: 'POST', headers, body: fd })
      } catch { /* fall through */ }
    }
    if (!res.ok) {
      const text = await res.text()
      let msg = text
      try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
      throw new ApiError(res.status, msg || res.statusText)
    }
    return res.json()
  },
  deletePartPhoto: (projectId: string, fileId: string, storageKey: string) =>
    request<ApiFileWithMesh>(`/api/projects/${projectId}/files/${fileId}/photos?key=${encodeURIComponent(storageKey)}`,
      { method: 'DELETE' }),
  setPrimaryPartPhoto: (projectId: string, fileId: string, storageKey: string) =>
    request<ApiFileWithMesh>(`/api/projects/${projectId}/files/${fileId}/photos/primary?key=${encodeURIComponent(storageKey)}`,
      { method: 'PATCH' }),

  // ---- Library: Part 3D model ----
  // Thin wrapper around the chunked upload helper that returns a
  // {storage_key, mime_type} pair. Used by LibraryEditor's "Attach model"
  // affordance — the workspace store also has a higher-level
  // `replacePartModel` action that wraps this with revision recording.
  uploadPartModel: async (
    projectId: string,
    blob: Blob,
    fileName?: string,
    opts: UploadAssetChunkedOpts = {},
  ): Promise<ChunkedUploadResult> => {
    const file = blob instanceof File
      ? blob
      : new File([blob], fileName || 'model.step', { type: blob.type || 'model/step' })
    const created = await uploadAssetChunked(projectId, file, {
      kind: 'step',
      parent_id: null,
      ...opts,
    })
    return created
  },

  // ---- File revisions (per-file undo history) ----
  getRevisionsSize: (projectId: string) =>
    request<RevisionsSize>(`/api/projects/${projectId}/revisions/size`),
  listRevisions: (projectId: string, fileId: string, limit?: number) =>
    request<FileRevision[]>(`/api/projects/${projectId}/files/${fileId}/revisions${limit ? `?limit=${limit}` : ''}`),
  getRevision: (projectId: string, fileId: string, revisionId: string) =>
    request<FileRevision>(`/api/projects/${projectId}/files/${fileId}/revisions/${revisionId}`),
  // Lazy-load the full reconstructed content for a single revision.
  // The list endpoint intentionally omits content; call this only when the
  // user explicitly requests it (e.g. "Show full content" in the panel).
  getRevisionContent: (projectId: string, fileId: string, revisionId: string) =>
    request<FileRevision & { content: string }>(`/api/projects/${projectId}/files/${fileId}/revisions/${revisionId}/content`),
  restoreRevision: (projectId: string, fileId: string, revisionId: string) =>
    request<ApiFileWithMesh>(`/api/projects/${projectId}/files/${fileId}/restore/${revisionId}`, { method: 'POST' }),

  // Purge old per-keystroke revision history for a project.
  // keepLast: number of most-recent revisions to retain per file (min 1).
  purgeRevisions: (projectId: string, { keepLast = 5 }: { keepLast?: number } = {}) =>
    request<PurgeRevisionsResult>(
      `/api/projects/${projectId}/revisions?keep_last=${encodeURIComponent(String(keepLast))}&confirm=PURGE`,
      { method: 'DELETE' },
    ),

  // ---- Avatar ----
  // Upload a new avatar from the user's local picker. The backend
  // resizes server-side (256x256, JPEG q=85) and returns the updated
  // user row with a freshly resolved avatar_url.
  uploadAvatar: async (blob: Blob & { name?: string }): Promise<ApiUser> => {
    const fd = new FormData()
    const name = (blob && blob.name) || 'avatar.jpg'
    fd.append('file', blob, name)
    const url = `${API_URL}/api/me/avatar`
    const token = useAuth.getState().accessToken
    const headers: Record<string, string> = {}
    if (token) headers.authorization = `Bearer ${token}`
    let res = await fetch(url, { method: 'POST', headers, body: fd })
    if (res.status === 401 && useAuth.getState().refreshToken) {
      try {
        const newToken = await refreshAccessToken()
        headers.authorization = `Bearer ${newToken}`
        res = await fetch(url, { method: 'POST', headers, body: fd })
      } catch { /* fall through */ }
    }
    if (!res.ok) {
      const text = await res.text()
      let msg = text
      try { msg = JSON.parse(text).error || text } catch { /* ignore */ }
      throw new ApiError(res.status, msg || res.statusText)
    }
    return res.json()
  },
  // Returns the updated user, same as uploadAvatar — DELETE /api/me/avatar responds with the
  // full user row, not 204. Was declared `void`, which made the Profile page's use of the
  // response un-typeable.
  deleteAvatar: () => request<ApiUser>('/api/me/avatar', { method: 'DELETE' }),

  // ---- API Tokens ----
  createAPIToken: (name: string) => request<ApiToken>('/api-tokens', { method: 'POST', body: { name } }),
  listAPITokens: () => request<ApiToken[]>('/api-tokens'),
  revokeAPIToken: (tokenID: string) => request<void>(`/api-tokens/${encodeURIComponent(tokenID)}`, { method: 'DELETE' }),

  // ---- Admin: distributor credentials (Library Phase 2) ----
  // All admin-only (account_role='admin'). The list endpoint returns
  // unconfigured rows too, so the UI can render a stub "configure"
  // affordance for each known distributor.
  admin: {
    listDistributors: () => request<AdminDistributor[]>('/api/admin/distributors'),
    updateDistributor: (name: string, payload: Record<string, unknown>) =>
      request<AdminDistributor>(`/api/admin/distributors/${encodeURIComponent(name)}`, {
        method: 'PUT',
        body: payload,
      }),
    deleteDistributor: (name: string) =>
      request<void>(`/api/admin/distributors/${encodeURIComponent(name)}`, {
        method: 'DELETE',
      }),

    // Library Phase 3: verified-publisher curation. The backend
    // returns user rows with a library_count rollup and a
    // next_cursor for pagination. Search filters on email + name
    // server-side; verified_only=true narrows to flagged accounts.
    listPublishers: ({ search, verifiedOnly, cursor, limit }: {
      search?: string
      verifiedOnly?: boolean
      cursor?: string
      limit?: number
    } = {}) => {
      const qs = []
      if (search) qs.push(`search=${encodeURIComponent(search)}`)
      if (verifiedOnly) qs.push('verified_only=true')
      if (cursor) qs.push(`cursor=${encodeURIComponent(cursor)}`)
      if (limit) qs.push(`limit=${limit}`)
      const tail = qs.length ? `?${qs.join('&')}` : ''
      return request<AdminPublishersPage>(`/api/admin/publishers${tail}`)
    },
    setPublisherVerified: (userId: string, isVerified: boolean) =>
      request<AdminPublisher>(`/api/admin/publishers/${encodeURIComponent(userId)}`, {
        method: 'PUT',
        body: { is_verified_publisher: !!isVerified },
      }),
  },

  // ---- Library Phase 2: per-Part distributor refresh ----
  // Synchronous. The endpoint returns {updated: N, content: "<JSON>"}.
  refreshPartDistributors: (projectId: string, fileId: string) =>
    request<{ updated: number; content: string }>(
      `/api/projects/${projectId}/files/${fileId}/distributors/refresh`,
      { method: 'POST' },
    ),

  // ---- Tolerance stack-up run ----
  // Response shape is not documented in api.js and not modeled in
  // src/types/api.ts — genuinely open-ended here, same as ToolCallResult.
  runTolerance: (projectId: string, fileId: string, { method = 'monte_carlo', samples = 10000, rss_k = 3.0 }: {
    method?: string
    samples?: number
    rss_k?: number
  } = {}) =>
    request<unknown>(
      `/api/projects/${projectId}/files/${fileId}/tolerance/run`,
      { method: 'POST', body: { method, samples, rss_k } },
    ),

  // ---- FreeCAD import ----
  // Kick off a FreeCAD import given a blob/asset id returned by uploadAsset
  // or uploadAssetChunked. Calls the import_freecad_project LLM tool via the
  // standard project-level tool-call route.
  importFreecadProject: (projectId: string, fileBlobId: string, opts: { importFolder?: string; mode?: string } = {}) =>
    request<ImportResult>(`/api/projects/${projectId}/imports/freecad`, {
      method: 'POST',
      body: {
        file_blob_id: fileBlobId,
        import_folder: opts.importFolder ?? '/freecad_import',
        mode: opts.mode ?? 'project',
      },
    }),

  // ---- IFC import ----
  // Import a .ifc file into a project as a .bim architecture file.
  importIFC: (projectId: string, fileBlobId: string, opts: { importFolder?: string; mode?: string } = {}) =>
    request<ImportResult>(`/api/projects/${projectId}/imports/ifc`, {
      method: 'POST',
      body: {
        file_blob_id: fileBlobId,
        import_folder: opts.importFolder ?? '/ifc_import',
        mode: opts.mode ?? 'project',
      },
    }),

  // ---- BIM → IFC compile ----
  // Compiles a .bim file's content to IFC4 (via IfcOpenShell) for the viewer.
  compileIfc: (bimContent: string) =>
    request<CompileIfcResult>(`/compile-ifc`, { method: 'POST', body: { bim_content: bimContent } }),

  // ---- Topology optimisation run ----
  // POSTs to the kerf-api thin handler which forwards to pyworker /run-topo.
  runTopo: (projectId: string, fileId: string) =>
    request<TopoRunResult>(`/api/projects/${projectId}/files/${fileId}/topo/run`, { method: 'POST' }),

  // ---- Wiring diagram render ----
  // POSTs to the kerf-api thin handler which forwards to pyworker /run-wireviz.
  runWireviz: (projectId: string, fileId: string) =>
    request<WirevizResult>(`/api/projects/${projectId}/files/${fileId}/wiring/run`, { method: 'POST' }),

  // ---- PLC lint ----
  // POSTs ST source directly to pyworker POST /lint-plc via the kerf-api thin handler.
  lintPLC: (projectId: string, source: string) =>
    request<PlcLintResult>(`/api/projects/${projectId}/plc/lint`, {
      method: 'POST',
      body: { source },
    }),

  // ---- 3D-print slicing (kerf-slicing plugin, CuraEngine subprocess) ----
  // Slices the STL mesh referenced by the .print config file via the
  // pyworker POST /run-print-slice route. Returns G-code metadata + preview.
  runPrintSlice: (projectId: string, fileId: string) =>
    request<PrintSliceResult>(`/api/projects/${projectId}/files/${fileId}/print-slice`, {
      method: 'POST',
    }),

  // ---- Jewelry metal-cost estimator ----
  // Pure-math endpoint — no file required.
  jewelryMetalCost: (projectId: string, params: Record<string, unknown>) =>
    request<JewelryCostResult>(`/api/projects/${projectId}/jewelry/metal-cost`, {
      method: 'POST',
      body: params,
    }),

  // ---- Jewelry full quote ----
  // Full jeweller's quote: metal casting + stone line items + labour/setting/
  // finishing + markup. The backend /jewelry/metal-cost endpoint handles the
  // metal weight and comparison table; stone/labour/markup are computed
  // client-side by jewelryQuoteLocal() in JewelryCostPanel.jsx and stitched
  // into the final result. This method sends all params so the backend can
  // compute the metal cost portion; unknown params are silently ignored.
  //
  // The returned `estimate` will be the casting_cost schema (legacy mode)
  // from the backend; JewelryCostPanel augments it with stone/labour/markup
  // to produce the full_quote result on the client.
  jewelryQuote: (projectId: string, params: Record<string, unknown>) =>
    request<JewelryCostResult>(`/api/projects/${projectId}/jewelry/metal-cost`, {
      method: 'POST',
      body: params,
    }),

  // ---- Assembly clash detection ----
  // Runs OBB-SAT + BVH clash detection on the components of a given assembly
  // file.  The backend fetches bbox/transform data from the file store and
  // runs kerf_cad_core.clash.detect.clash_detect inline.
  runClashDetect: (projectId: string, fileId: string, opts: { minClearance?: number } = {}) =>
    request<ClashDetectResult>(`/api/projects/${projectId}/files/${fileId}/clash`, {
      method: 'POST',
      body: { min_clearance: opts.minClearance ?? 0 },
    }),

  // ---- Building energy simulation ----
  // POST /api/projects/:pid/energy/building
  // Body: { zones: [...], location: {...}, export_idf: bool }
  buildingEnergy: (projectId: string, body: Record<string, unknown>) =>
    request<BuildingEnergyResult>(`/api/projects/${projectId}/energy/building`, {
      method: 'POST',
      body,
      timeoutMs: 30_000,
    }),

  // ---- PV partial-shading + bypass-diode + MPPT simulation ----
  // POST /api/projects/:pid/energy/pv-shading
  pvShading: (projectId: string, body: Record<string, unknown>) =>
    request<PvShadingResult>(`/api/projects/${projectId}/energy/pv-shading`, {
      method: 'POST',
      body,
      timeoutMs: 30_000,
    }),

  // ---------------------------------------------------------------------------
  // Generic LLM tool dispatcher — POST /api/tools/call
  // Used by SpiceRunPanel (and any other UI that needs to invoke a registered
  // backend tool directly without going through the chat thread flow).
  // ---------------------------------------------------------------------------
  // Generic in its result: this dispatcher can invoke ANY registered backend
  // tool, so the response shape is the caller's knowledge, not this module's.
  // Callers name it — `api.callTool<SpiceToolResponse>(...)` — the same pattern
  // as `meshCache.get<T>` in src/lib/meshCache.ts, and for the same reason:
  // the concrete type is owned by the consumer, and src/lib must not reach into
  // it. Defaults to `ToolCallResult` so untyped callers keep the old behaviour.
  callTool: <T = ToolCallResult>(toolName: string, params: Record<string, unknown> = {}) =>
    request<T>('/api/tools/call', {
      method: 'POST',
      body: { tool: toolName, params },
    }),
}

// ---------------------------------------------------------------------------
// Chunked upload helpers (Phase 2)
// ---------------------------------------------------------------------------

// CHUNK_CONCURRENCY caps how many chunks can be in flight at once. 3 is the
// sweet spot for typical home-broadband upstream — more pipelined transfers
// rarely beat the single-stream throughput once link buffer fills.
const CHUNK_CONCURRENCY = 3
// Per-chunk retry policy. Three retries with exponential backoff (250 / 500 /
// 1000 ms) before we surface the error to the caller.
const CHUNK_RETRIES = 3

// Compute SHA-256 over a File, returning a 64-char lowercase hex digest.
// Web Crypto's `crypto.subtle.digest` doesn't expose an incremental API, so
// we feed it the entire ArrayBuffer in one shot. Fine within the 200 MB cap;
// switch to `js-sha256` streaming if we ever raise the cap.
async function sha256OfFile(file: File): Promise<string> {
  const buf = await file.arrayBuffer()
  const digest = await crypto.subtle.digest('SHA-256', buf)
  const bytes = new Uint8Array(digest)
  let hex = ''
  for (let i = 0; i < bytes.length; i++) {
    hex += bytes[i].toString(16).padStart(2, '0')
  }
  return hex
}

// authedFetch: a thin fetch wrapper that injects the bearer token and
// transparently refreshes on 401. Returns the raw Response so the caller
// can decide what to do (we use it for both JSON and 204 responses).
async function authedFetch(url: string, init: RequestInit = {}): Promise<Response> {
  const token = useAuth.getState().accessToken
  const headers: Record<string, string> = { ...(init.headers as Record<string, string> || {}) }
  if (token) headers.authorization = `Bearer ${token}`
  let res = await fetch(url, { ...init, headers })
  if (res.status === 401 && useAuth.getState().refreshToken) {
    try {
      const newToken = await refreshAccessToken()
      headers.authorization = `Bearer ${newToken}`
      res = await fetch(url, { ...init, headers })
    } catch { /* fall through to caller */ }
  }
  return res
}

async function readErrorJSON(res: Response): Promise<ApiError> {
  const text = await res.text().catch(() => '')
  let msg = text || res.statusText
  let code: string | undefined
  try {
    const j = JSON.parse(text)
    msg = j.error || msg
    code = j.code
  } catch { /* not JSON */ }
  const err = new ApiError(res.status, msg)
  if (code) err.code = code
  return err
}

interface UploadAssetChunkedOpts {
  kind?: string
  parent_id?: string | null
  onProgress?: (progress: { received: number; total: number; bytes: number }) => void
  onInit?: (info: { uploadId: string; chunkSize: number; totalChunks: number }) => void
  signal?: AbortSignal
}

// uploadAssetChunked: the main entry point — see api.uploadAssetChunked.
async function uploadAssetChunked(
  projectId: string,
  file: File,
  { kind = 'step', parent_id = null, onProgress, onInit, signal }: UploadAssetChunkedOpts = {},
): Promise<ChunkedUploadResult> {
  if (!file) throw new Error('uploadAssetChunked: file required')

  const sha256 = await sha256OfFile(file)

  // 1. Init / resume.
  const initRes = await authedFetch(`${API_URL}/api/projects/${projectId}/uploads`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({
      filename: file.name,
      size: file.size,
      mime: file.type || 'model/step',
      sha256,
    }),
  })
  if (!initRes.ok) throw await readErrorJSON(initRes)
  const init: UploadInitResponse = await initRes.json()
  const { upload_id: uploadId, chunk_size: chunkSize, total_chunks: totalChunks } = init
  const received = new Set((init.received_chunks || []).map((n) => Number(n)))
  // Surface the upload_id so the caller (e.g. workspace store) can wire a
  // proper DELETE on cancel.
  if (typeof onInit === 'function') {
    try { onInit({ uploadId, chunkSize, totalChunks }) } catch { /* swallow */ }
  }

  // Helper: drive a clean abort by DELETE-ing the session on the server,
  // then surfacing a recognisable error to the caller.
  async function abortAndThrow(): Promise<never> {
    try {
      await authedFetch(`${API_URL}/api/projects/${projectId}/uploads/${uploadId}`, {
        method: 'DELETE',
      })
    } catch { /* best-effort */ }
    const err: Error & { aborted?: boolean } = new Error('upload aborted')
    err.aborted = true
    throw err
  }

  // 2. If the server says we're already complete (idempotent re-upload of
  // the same SHA), skip straight to finalize.
  if (!init.complete) {
    // 3. Build the missing-chunk worklist.
    const missing: number[] = []
    for (let i = 0; i < totalChunks; i++) {
      if (!received.has(i)) missing.push(i)
    }

    // 4. Bounded concurrency loop. We pull from the worklist via a shared
    // index so each "worker" simply asks for the next item to do.
    const total = totalChunks
    const fireProgress = () => {
      if (typeof onProgress === 'function') {
        const r = received.size
        onProgress({
          received: r,
          total,
          bytes: Math.min(file.size, r * chunkSize),
        })
      }
    }
    fireProgress() // initial tick (for resumed uploads, this could be > 0).

    if (signal?.aborted) await abortAndThrow()

    let nextIdx = 0
    let firstError: (Error & { aborted?: boolean }) | null = null
    const workers: Promise<void>[] = []
    const concurrency = Math.min(CHUNK_CONCURRENCY, missing.length || 1)
    for (let w = 0; w < concurrency; w++) {
      workers.push((async () => {
        while (firstError == null) {
          if (signal?.aborted) {
            firstError = new Error('upload aborted') as Error & { aborted?: boolean }
            firstError.aborted = true
            return
          }
          const myIdx = nextIdx++
          if (myIdx >= missing.length) return
          const chunkIndex = missing[myIdx]
          const start = chunkIndex * chunkSize
          const end = Math.min(file.size, start + chunkSize)
          const blob = file.slice(start, end)
          try {
            await uploadOneChunk(projectId, uploadId, chunkIndex, blob, signal)
            received.add(chunkIndex)
            fireProgress()
          } catch (err: unknown) {
            firstError = err as Error & { aborted?: boolean }
            return
          }
        }
      })())
    }
    await Promise.all(workers)
    if (firstError) {
      const err: Error & { aborted?: boolean } = firstError
      if (err.aborted || signal?.aborted) await abortAndThrow()
      throw err
    }
  }

  if (signal?.aborted) await abortAndThrow()

  // 5. Finalize.
  const finRes = await authedFetch(`${API_URL}/api/projects/${projectId}/uploads/${uploadId}/finalize`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ kind, parent_id }),
  })
  if (!finRes.ok) throw await readErrorJSON(finRes)
  return finRes.json()
}

// uploadOneChunk: PUT a single chunk with retries + exponential backoff.
async function uploadOneChunk(
  projectId: string,
  uploadId: string,
  chunkIndex: number,
  blob: Blob,
  signal: AbortSignal | undefined,
): Promise<void> {
  let attempt = 0
  let lastErr: unknown
  while (attempt <= CHUNK_RETRIES) {
    if (signal?.aborted) throw new Error('upload aborted')
    try {
      const url = `${API_URL}/api/projects/${projectId}/uploads/${uploadId}/chunks/${chunkIndex}`
      const res = await authedFetch(url, {
        method: 'PUT',
        headers: { 'content-type': 'application/octet-stream' },
        body: blob,
        signal,
      })
      if (res.ok || res.status === 204) return
      // Non-retryable client errors: don't bother retrying.
      if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
        throw await readErrorJSON(res)
      }
      lastErr = await readErrorJSON(res)
    } catch (err: unknown) {
      lastErr = err
    }
    attempt++
    if (attempt > CHUNK_RETRIES) break
    const backoffMs = 250 * (2 ** (attempt - 1))
    await new Promise((r) => setTimeout(r, backoffMs))
  }
  throw lastErr || new Error(`chunk ${chunkIndex} upload failed`)
}

// cancelUpload: best-effort DELETE of an in-flight upload session.
export async function cancelUpload(projectId: string, uploadId: string): Promise<void> {
  try {
    await authedFetch(`${API_URL}/api/projects/${projectId}/uploads/${uploadId}`, {
      method: 'DELETE',
    })
  } catch { /* best-effort */ }
}
