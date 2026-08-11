// api.ts — response/request shapes for src/lib/api.js (T-501).
//
// src/lib/api.js is a thin fetch wrapper: most of its ~80 methods just
// `return request(path, { method, body })` without touching the parsed JSON,
// so the exact response *row* shape for CRUD resources (Workspace, Project,
// ProjectFile, Thread, ProjectMember, ShareLink, Revision, ...) is not
// visible in api.js itself. Those shapes below are grounded in how the
// consuming code (src/store/workspace.js, src/components/*.jsx) destructures
// the parsed responses — cited per type. Where a field is exercised only via
// `?.`/`|| default` it is marked optional; fields with no direct evidence in
// consumer code beyond the request-body shape are the narrowest common
// reading, flagged inline.
//
// Endpoints with an explicit `// Returns {...}` / `// Response: {...}`
// comment in api.js (jewelry, energy, topo, wireviz, PLC lint, print-slice,
// clash detect, FreeCAD/IFC import, revisions size/purge) are transcribed
// directly from that comment, which is the strongest evidence available.
//
// There is no common envelope (`{ok,data,error}` or similar) — `request()`
// in api.js returns the parsed JSON body as-is on 2xx, `null` on 204, and
// throws `ApiError` (status + message, `.code` optionally set by
// readErrorJSON()) on non-2xx. `ApiError` is a runtime class owned by
// api.js; T-501 does not redeclare it here (types-only file, see
// docs/typescript-migration.md's T-501 conventions).

// ---------------------------------------------------------------------------
// Auth / account (api.js "---- Auth ----", store/auth.js setSession callers)
// ---------------------------------------------------------------------------

// Fields confirmed via src/store/auth.js (setSession's accessToken/
// refreshToken/user destructuring) and direct `user.*` accesses in
// src/components/Layout.jsx (avatar_url, email_verified) and api.js's own
// admin.listDistributors/listPublishers comments (account_role, is_verified_publisher).
export interface ApiUser {
  id: string
  email: string
  name?: string
  avatar_url?: string | null
  /** Only 'admin' is checked against in the frontend (api.js admin.* comment); other values are opaque strings. */
  account_role?: string
  email_verified?: boolean
  is_verified_publisher?: boolean
}

export interface AuthSession {
  access_token: string
  refresh_token: string
  user: ApiUser
}

// ---------------------------------------------------------------------------
// Workspaces (api.js "---- Workspaces ----", src/components/WorkspaceSwitcher.jsx)
// ---------------------------------------------------------------------------

export interface ApiWorkspace {
  id: string
  slug: string
  name: string
  /** Caller's role in this workspace; WorkspaceSwitcher.jsx falls back to 'member' when absent. */
  my_role?: string
}

export interface WorkspaceMember {
  user_id: string
  email: string
  name?: string
  role: string
}

// ---------------------------------------------------------------------------
// Projects (api.js "---- Projects ----")
// ---------------------------------------------------------------------------

/** createProject's body shape (api.js ~line 211); the response row is inferred to mirror it plus `id`. */
/**
 * Must mirror STARTER_SEEDS in packages/kerf-api/src/kerf_api/routes.py, which is also what
 * STARTER_OPTIONS offers in the create dialog. Previously listed only jscad/circuit/blank, so
 * assembly, feature and drawing — all selectable in the UI and accepted by the server — were
 * not expressible.
 */
export type ProjectStarter =
  | 'jscad'
  | 'assembly'
  | 'feature'
  | 'drawing'
  | 'circuit'
  | 'blank'

export interface ApiProject {
  id: string
  workspace_id: string
  name: string
  description?: string
  tags?: string[]
  starter?: ProjectStarter
  created_at?: string
  updated_at?: string
}

// ---------------------------------------------------------------------------
// Files (api.js "---- Files / Assemblies ----", src/store/workspace.js's
// `file.kind`/`file.parent_id`/`file.content` accesses — kind union
// enumerated from every `file.kind === '...'` / `f.kind === '...'` literal
// found there, e.g. src/store/workspace.js:102-115.)
// ---------------------------------------------------------------------------

export type FileKind =
  | 'file'
  | 'folder'
  | 'part'
  | 'assembly'
  | 'drawing'
  | 'sketch'
  | 'feature'
  | 'circuit'
  | 'equations'
  | 'script'
  | 'subd'
  | 'mesh'
  | 'text'
  | 'material'
  /** JSCAD script files — see `kind === 'jscad'` checks in src/store/workspace.js. */
  | 'jscad'
  /** Wiring-harness diagram files — see `kind === 'wiring'` checks in src/store/workspace.js. */
  | 'wiring'
  /** Set by uploadAsset's default `kind = 'step'` (api.js ~line 273). */
  | 'step'

export interface ApiFile {
  id: string
  project_id?: string
  name: string
  kind: FileKind
  parent_id: string | null
  content?: string
  created_at?: string
  updated_at?: string
}

// ---------------------------------------------------------------------------
// Threads / chat (api.js "---- Chat ----" / "---- Threads ----")
// ---------------------------------------------------------------------------

export interface ApiThread {
  id: string
  project_id?: string
  title?: string
  file_id?: string | null
  model?: string
  created_at?: string
}

export interface ApiChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  part_refs?: unknown[]
  model?: string
  created_at?: string
}

/** streamMessage()'s per-event payload — see api.js's own JSDoc on that method. */
export interface ChatStreamEvent {
  event: string
  data: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Members / share links (api.js "---- Members ----" / "---- Share Links ----",
// src/components/ShareModal.jsx's ROLES/LINK_ROLES literal arrays)
// ---------------------------------------------------------------------------

/** ShareModal.jsx: `const ROLES = ['viewer', 'editor', 'owner']`. */
export type ProjectRole = 'viewer' | 'editor' | 'owner'

export interface ProjectMember {
  user_id: string
  email: string
  name?: string
  role: ProjectRole
}

/** ShareModal.jsx: `const LINK_ROLES = ['viewer', 'editor']` — links can't grant 'owner'. */
export type ShareLinkRole = 'viewer' | 'editor'

export interface ShareLink {
  id: string
  token?: string
  role: ShareLinkRole
  expires_at?: string | null
  max_uses?: number | null
  uses?: number
}

export interface ShareInfo {
  project_id: string
  role: ShareLinkRole
  project_name?: string
}

// ---------------------------------------------------------------------------
// File revisions (api.js "---- File revisions ----", src/lib/revisionMeta.js's
// documented `source` vocabulary, src/components/RevisionDrawer.jsx's `rev.*` accesses)
// ---------------------------------------------------------------------------

/** The exact 4 values documented in src/lib/revisionMeta.js's header comment. */
export type RevisionSource = 'user' | 'llm' | 'tool' | 'restore'

export interface FileRevision {
  id: string
  source: RevisionSource
  created_at: string
  user_name?: string
  user_avatar_url?: string
  /** List endpoint omits full content by design (api.js getRevisionContent comment); use getRevisionContent for that. */
  content_preview?: string
  diff_added?: number
  diff_removed?: number
  added_lines?: number
  removed_lines?: number
}

export interface RevisionsSize {
  total_bytes: number
  revision_count: number
  by_file: Array<{ file_id: string; file_name: string; bytes: number; count: number }>
}

export interface PurgeRevisionsResult {
  removed_rows: number
  freed_bytes: number
}

// ---------------------------------------------------------------------------
// Activity timeline (api.js getActivity comment: "merged feed of recent
// events (file revisions, chat messages, file lifecycle, project_created)";
// src/components/ActivityTimeline.jsx's `ev.kind`/`ev.source`/`ev.file`/`ev.thread` accesses)
// ---------------------------------------------------------------------------

export type ActivityKind = 'edit' | 'file_created' | 'file_deleted' | 'chat' | 'project_created'

export interface ActivityEvent {
  kind: ActivityKind
  created_at: string
  /** Present on 'edit' events; same vocabulary as FileRevision.source. */
  source?: RevisionSource
  user?: { name?: string; email?: string; avatar_url?: string }
  file?: { id: string; kind?: FileKind; name?: string }
  thread?: { id: string; title?: string }
  content_preview?: string
}

export interface ActivityPage {
  events: ActivityEvent[]
  /** ISO timestamp; pass as `before` to page further back (api.js getActivity comment). */
  next_cursor: string | null
}

// ---------------------------------------------------------------------------
// Bill of materials (api.js "---- Bill of Materials ----",
// src/store/workspace.js's loadBOM destructuring, src/components/BOMPanel.jsx's CSV export)
// ---------------------------------------------------------------------------

export interface BOMPart {
  name?: string
  description?: string
  category?: string
  manufacturer?: string
  mpn?: string
  value?: string
  datasheet_url?: string
}

export interface BOMDistributor {
  name?: string
  sku?: string
  url?: string
}

export interface BOMRow {
  part?: BOMPart
  primary_distributor?: BOMDistributor
  count?: number
  non_stocked?: boolean
  note?: string
  unit_price_usd?: number
  total_price_usd?: number
  file_id?: string
  path?: string
}

export interface BOMResult {
  rows: BOMRow[]
  total_price_usd?: number
  warnings: string[]
}

// ---------------------------------------------------------------------------
// Chunked upload (api.js uploadAssetChunked / uploadOneChunk / cancelUpload —
// fields destructured directly off `init`/`initRes.json()` in that function)
// ---------------------------------------------------------------------------

export interface UploadInitResponse {
  upload_id: string
  chunk_size: number
  total_chunks: number
  received_chunks?: number[]
  complete?: boolean
}

export interface UploadFinalizeResult {
  id: string
  kind: FileKind
  parent_id: string | null
  [field: string]: unknown
}

// ---------------------------------------------------------------------------
// API tokens / admin distributors & publishers (api.js "---- API Tokens ----" / "admin")
// ---------------------------------------------------------------------------

export interface ApiToken {
  id: string
  name: string
  created_at?: string
  /** Only ever returned once, at creation time. */
  token?: string
}

/** One saved LLM provider key. The key itself is never sent to the client. */
export interface ProviderKey {
  provider: string
  /** Last four characters behind bullets, e.g. "••••a91f". Empty when unreadable. */
  masked_key: string
  /** Gateway / OpenAI-compatible endpoint; null means the provider default. */
  base_url: string | null
  created_at?: string
  /**
   * False when the stored ciphertext won't decrypt — reachable without
   * corruption, since the encryption key derives from the server's jwt_secret
   * and rotating that orphans every saved key. The row is still listed so the
   * UI can prompt for a re-entry instead of silently forgetting.
   */
  readable: boolean
}

export interface ProviderKeysResponse {
  keys: ProviderKey[]
  supported_providers: string[]
  /** Providers the operator configured server-side; usable without a personal key. */
  operator_configured: string[]
}

export interface UsageTotals {
  events: number
  input_tokens: number
  output_tokens: number
  bytes_delta: number
  /** Informational estimate recorded at call time. Kerf bills nobody. */
  usd_cost: number
}

export interface UsageByModel {
  model: string
  events: number
  input_tokens: number
  output_tokens: number
  usd_cost: number
}

export interface UsageByKind {
  kind: string
  events: number
  input_tokens: number
  output_tokens: number
  bytes_delta: number
  usd_cost: number
}

export interface UsageDay {
  /** YYYY-MM-DD */
  day: string
  input_tokens: number
  output_tokens: number
  usd_cost: number
}

export interface UsageEvent {
  id: string
  kind: string
  model: string | null
  input_tokens: number
  output_tokens: number
  bytes_delta: number
  usd_cost: number
  payer: string
  project_id: string | null
  created_at: string
}

export interface UsageReport {
  days: number
  project_id: string | null
  totals: UsageTotals
  by_model: UsageByModel[]
  by_kind: UsageByKind[]
  daily: UsageDay[]
  recent: UsageEvent[]
}

export interface AdminDistributor {
  name: string
  /** True once the admin has entered credentials; unconfigured rows are still listed (api.js admin comment). */
  configured: boolean
  [field: string]: unknown
}

export interface AdminPublisher {
  id: string
  email: string
  name?: string
  library_count: number
  is_verified_publisher: boolean
}

export interface AdminPublishersPage {
  /** `rows`, not `publishers` — the server sends PublisherListResponse(rows=...). */
  rows: AdminPublisher[]
  next_cursor: string | null
}

// ---------------------------------------------------------------------------
// FreeCAD / IFC import (api.js "---- FreeCAD import ----" / "---- IFC import ----")
// ---------------------------------------------------------------------------

export interface ImportResult {
  created_file: ApiFile
  stats?: Record<string, unknown>
  warnings: string[]
  import_folder: string
}

export interface CompileIfcResult {
  ifc_base64: string
  warnings: string[]
  errors: string[]
}

// ---------------------------------------------------------------------------
// Topology optimisation / wiring / PLC / print-slice (each transcribed
// directly from its `// Returns {...}` comment in api.js)
// ---------------------------------------------------------------------------

export type TopoRunResult =
  | { job_id: string; status: string }
  | { status: 'pending' }

export interface WirevizResult {
  svg: string | null
  warnings: string[]
}

export interface PlcLintResult {
  diagnostics: unknown[]
  warnings: unknown[]
}

export interface PrintSliceResult {
  gcode: string
  layer_count: number
  print_time_s: number
  filament_mm: number
  gcode_bytes: number
  warnings: string[]
  error: string | null
}

// ---------------------------------------------------------------------------
// Jewelry metal cost / quote (api.js "---- Jewelry metal-cost estimator ----" / "---- Jewelry full quote ----")
// ---------------------------------------------------------------------------

export interface JewelryMetalEstimate {
  net_grams: number
  net_dwt: number
  net_ozt: number
  gross_grams: number
  gross_dwt: number
  gross_ozt: number
  metal_cost: number
  labor: number
  finishing: number
  total_cost: number
  allowance_pct: number
  label: string
}

export interface JewelryCostResult {
  estimate: JewelryMetalEstimate
  comparison?: unknown[]
}

// ---------------------------------------------------------------------------
// Assembly clash detection (api.js "---- Assembly clash detection ----")
// ---------------------------------------------------------------------------

export interface ClashDetectResult {
  ok: boolean
  clashes: unknown[]
  clash_count: number
  by_discipline_pair: Record<string, number>
  errors: unknown[]
}

// ---------------------------------------------------------------------------
// Energy simulation (api.js "---- Building energy simulation ----" / "---- PV partial-shading ... ----")
// ---------------------------------------------------------------------------

export interface BuildingEnergyResult {
  totals: Record<string, unknown>
  monthly: unknown[]
  idf?: string
}

export interface PvShadingResult {
  string_gmpp_p_w: number
  mismatch_loss_pct: number
  annual_yield_yr1_kWh: number
  /** Latitude-aware TMY monthly breakdown (api.js pvShading comment). */
  monthly_yield: unknown[]
  [field: string]: unknown
}

// ---------------------------------------------------------------------------
// Generic LLM tool dispatcher (api.js "---- Generic LLM tool dispatcher ----")
// ---------------------------------------------------------------------------

/** callTool()'s response shape is whatever the named backend tool returns — genuinely open-ended per the dispatcher's design. */
export type ToolCallResult = unknown
