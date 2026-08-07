// Library-mapping persistence for `.circuit.tsx` files.
//
// We store the per-refdes → Library-Part-file-id mapping as a single line
// comment at the very top of the TSX source, in this exact format:
//
//   // kerf:library-mappings={"R1":"a-uuid","C1":"b-uuid"}
//
// Why a comment instead of a sidecar file:
//   - The TSX source is the single artifact users version-control / share.
//   - tscircuit and any TSX tooling ignore comments.
//   - Round-tripping is just regex match/replace; no schema migration.
//
// The marker line is recreated on every write — drift between content and
// mappings can't happen as long as you go through these helpers.

import type { JscadPart } from '../types/geometry.js'

/** refdes → Library-Part file id. */
export type LibraryMappings = Record<string, string>

const MARKER = '// kerf:library-mappings='

// parseLibraryMappings reads the marker comment and returns a refdes → file_id
// map. Missing or malformed → empty object (never throws). `content` is typed
// `unknown` (not `string`) because callers pass whatever a file's content
// field happens to hold, and this function's whole job is to defend against
// it being the wrong shape.
export function parseLibraryMappings(content: unknown): LibraryMappings {
  if (typeof content !== 'string' || content.length === 0) return {}
  // The marker must be on a line of its own. Use a forgiving scan over the
  // first ~32 lines so users editing inside the file don't displace it
  // beyond reach.
  const head = content.split('\n', 32)
  for (const line of head) {
    const trimmed = line.trimStart()
    if (!trimmed.startsWith(MARKER)) continue
    const json = trimmed.slice(MARKER.length).trim()
    try {
      const obj: unknown = JSON.parse(json)
      if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
        const out: LibraryMappings = {}
        for (const [k, v] of Object.entries(obj as Record<string, unknown>)) {
          if (typeof v === 'string' && v.length > 0) out[String(k)] = v
        }
        return out
      }
    } catch {
      return {}
    }
  }
  return {}
}

// writeLibraryMappings replaces (or inserts) the marker comment, returning the
// updated content. Empty mappings clear the marker entirely.
export function writeLibraryMappings(content: unknown, mappings: LibraryMappings | null | undefined): string {
  const safe = typeof content === 'string' ? content : ''
  const lines = safe.split('\n')
  // Locate an existing marker — only consider the first ~32 lines like above.
  let markerIdx = -1
  const scanLimit = Math.min(lines.length, 32)
  for (let i = 0; i < scanLimit; i++) {
    if (lines[i].trimStart().startsWith(MARKER)) { markerIdx = i; break }
  }
  const cleaned = mappings && Object.keys(mappings).length > 0
    ? Object.fromEntries(Object.entries(mappings).filter(([, v]) => typeof v === 'string' && v.length > 0))
    : {}
  if (Object.keys(cleaned).length === 0) {
    if (markerIdx === -1) return safe
    lines.splice(markerIdx, 1)
    // Drop a single leading blank line we may have inserted alongside the
    // marker so the file doesn't accumulate blank lines on toggle.
    if (markerIdx === 0 && lines[0] === '') lines.shift()
    return lines.join('\n')
  }
  const marker = MARKER + JSON.stringify(cleaned)
  if (markerIdx === -1) {
    // Insert at the very top so it's always near the imports.
    return marker + '\n' + safe
  }
  lines[markerIdx] = marker
  return lines.join('\n')
}

// setCircuitMapping is a tiny convenience: returns updated mappings and content
// for a single refdes change. Pass partFileId=null/undefined to clear.
export function setCircuitMapping(
  content: unknown,
  refdes: string,
  partFileId: string | null | undefined,
): { mappings: LibraryMappings; content: string } {
  const cur = parseLibraryMappings(content)
  if (partFileId) cur[refdes] = partFileId
  else delete cur[refdes]
  return { mappings: cur, content: writeLibraryMappings(content, cur) }
}

// resolveLibraryCadComponent looks up the Library Part file id for a given
// refdes given an already-parsed mappings object. Returns the file id string
// or null when no mapping exists (or the refdes / mappings argument is
// malformed). Pure — no IO, no fetch — so the 3D path can call it inline.
//
// This is the seam the 3D tab uses to decide whether a `cad_component` box
// should be visually flagged as "Library-linked" (and, in a future slice,
// replaced with the Part's real STEP/JSCAD geometry).
export function resolveLibraryCadComponent(refdes: unknown, mappings: unknown): string | null {
  if (typeof refdes !== 'string' || refdes.length === 0) return null
  if (!mappings || typeof mappings !== 'object' || Array.isArray(mappings)) return null
  const v = (mappings as Record<string, unknown>)[refdes]
  return typeof v === 'string' && v.length > 0 ? v : null
}

// ── Geometry substitution ────────────────────────────────────────────────────

export interface JscadSubstitution {
  kind: 'jscad'
  parts: JscadPart[]
}

export interface StepSubstitution {
  kind: 'step'
  parts: JscadPart[]
}

export type ComponentGeometrySubstitution = JscadSubstitution | StepSubstitution

/** Fetches STEP bytes for a Library Part's relative model path. */
export type FetchStep = (relativePath: string) => Promise<ArrayBuffer>

interface LibraryPartJson {
  model_3d?: unknown
  model_3d_paths?: unknown
  [key: string]: unknown
}

// substituteComponentGeometry — full substitution seam for a Library Part.
//
// Given a Library Part file's content string and an optional async fetchStep
// function `(relativePath) => ArrayBuffer`, tries to resolve real geometry:
//
//   1. If the Part JSON has a `model_3d` JSCAD source → delegates to
//      evalLibraryModel3D and returns `{ kind: 'jscad', parts: [...] }`.
//   2. If the Part JSON has a `model_3d_paths` with a .step/.stp entry and
//      `fetchStep` is provided → fetches the bytes, parses via loadStep, and
//      returns `{ kind: 'step', parts: [...] }`.
//   3. Otherwise returns null (caller should show indicator chip).
//
// Cache: the STEP bytes cache lives in stepLoader.js (keyed by SHA-256 of
// the buffer). JSCAD caching is handled by the fetchCacheRef in
// CircuitEditor.jsx. This function is pure-async with no internal state.
//
// Exported for testing. Callers that don't need STEP substitution can omit
// fetchStep (pass null / undefined) — the function will still try JSCAD.
export async function substituteComponentGeometry(
  content: unknown,
  fetchStep?: FetchStep | null,
): Promise<ComponentGeometrySubstitution | null> {
  if (typeof content !== 'string' || content.length === 0) return null
  let raw: LibraryPartJson
  try { raw = JSON.parse(content) } catch { return null }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null

  // 1. JSCAD path — prefer over STEP (client-side, no extra round-trip).
  const src = raw.model_3d
  if (typeof src === 'string' && src.length > 0) {
    const looksLikeJs = /\bfunction\b|=>|\bexport\b/.test(src)
    if (looksLikeJs) {
      const res = await evalLibraryModel3D(content)
      if (res) return { kind: 'jscad', parts: res.parts }
    }
    // If model_3d is present but is a URL/path (not JS), fall through to STEP
    // detection below rather than silently doing nothing.
  }

  // 2. STEP path — requires a fetchStep injector (so tests can stub it).
  if (typeof fetchStep === 'function') {
    const paths = Array.isArray(raw.model_3d_paths) ? (raw.model_3d_paths as unknown[]) : []
    // Also accept a model_3d that looks like a /api/blobs/... URL.
    const maybeUrl = typeof raw.model_3d === 'string' ? raw.model_3d : null
    const stepUrl = maybeUrl && /\.(step|stp)($|\?)/i.test(maybeUrl) ? maybeUrl : null
    const stepPath = stepUrl || paths.find(
      (p): p is string => typeof p === 'string' && /\.(step|stp)$/i.test(p),
    )
    if (stepPath) {
      try {
        const buf = await fetchStep(stepPath)
        if (buf && buf.byteLength > 0) {
          // Lazy-import stepLoader so the module stays tree-shakable.
          const { loadStep } = await import('./stepLoader.js')
          const res = await loadStep(buf)
          if (res && Array.isArray(res.parts) && res.parts.length > 0) {
            return { kind: 'step', parts: res.parts }
          }
        }
      } catch (err) {
        if (typeof console !== 'undefined') {
          console.warn('substituteComponentGeometry: STEP load failed:', err)
        }
      }
    }
  }

  return null
}

// evalLibraryModel3D — parse a Library Part file's content and, if it carries
// a JSCAD-source `model_3d` field, evaluate it via the standard jscadRunner
// and return `{ parts: [{id, geom}, ...] }`. Returns null in every failure
// mode so callers fall through to the teal box approximation:
//   - empty / non-string content
//   - JSON parse fails
//   - no `model_3d` field, or the field isn't a non-empty string
//   - JSCAD eval throws or comes back with an `error`
//   - JSCAD eval comes back with zero parts
//
// We deliberately don't try to handle STEP / STL URLs here (a `model_3d`
// that looks like a `/api/blobs/...` path) — those need an OCCT-side parser
// and are a separate slice. The detection is "starts with `function`,
// `export`, `(`, or `=>` *somewhere*" — a coarse heuristic that's good
// enough to skip the obvious URL case without false-positives on real
// JSCAD source.
//
// Async because runJscad is async (worker-driven, with a main-thread
// fallback under vitest). Caller must await.
export async function evalLibraryModel3D(content: unknown): Promise<{ parts: JscadPart[] } | null> {
  if (typeof content !== 'string' || content.length === 0) return null
  let raw: LibraryPartJson
  try { raw = JSON.parse(content) } catch { return null }
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const src = raw.model_3d
  if (typeof src !== 'string' || src.length === 0) return null
  // Skip URL-shaped values — STEP/STL substitution is out of scope here.
  // A JSCAD source has executable JS (`function`, `=>`, or `export`); a
  // URL/path doesn't. We accept anything that smells like JS source.
  const looksLikeJs = /\bfunction\b|=>|\bexport\b/.test(src)
  if (!looksLikeJs) return null
  // Cheap parse-check — `new Function` throws SyntaxError synchronously
  // on malformed input. Strip `export default` first since `new Function`
  // doesn't permit it. This catches obvious typos before they hand the
  // source to runJscad (which can hang in worker mode without a timeout).
  const probe = 'return ' + src.replace(/^\s*export\s+(default\s+)?/, '')
  try { new Function(probe) } catch {
    if (typeof console !== 'undefined') {
      console.warn('evalLibraryModel3D: source has syntax errors; falling through')
    }
    return null
  }
  // Lazy import so this module stays tree-shakable for non-3D callers and
  // tests that don't exercise the JSCAD path don't pay the import cost.
  // jscadRunner.js is not part of this slice (T-506/507) and stays untyped,
  // so its return shape is asserted against the shared JscadRunResult union.
  let runJscad: (src: string) => Promise<{ parts?: JscadPart[]; error?: string; stale?: boolean } | null | undefined>
  try {
    ({ runJscad } = await import('./jscadRunner.js'))
  } catch (err) {
    if (typeof console !== 'undefined') {
      console.warn('evalLibraryModel3D: failed to load jscadRunner:', err)
    }
    return null
  }
  let res: { parts?: JscadPart[]; error?: string; stale?: boolean } | null | undefined
  try {
    // Race against a 3s timeout — runJscad can hang in test environments
    // (worker stub, no Worker context). Falling through is fine; the teal
    // box is the visible payoff.
    res = await Promise.race([
      runJscad(src),
      new Promise<never>((_, reject) =>
        setTimeout(() => reject(new Error('runJscad timeout')), 3000),
      ),
    ])
  } catch (err) {
    if (typeof console !== 'undefined') {
      console.warn('evalLibraryModel3D: runJscad failed:', err)
    }
    return null
  }
  if (!res || res.error || res.stale) {
    if (res && res.error && typeof console !== 'undefined') {
      console.warn('evalLibraryModel3D: JSCAD eval error:', res.error)
    }
    return null
  }
  const parts = Array.isArray(res.parts) ? res.parts.filter((p) => p && p.geom) : []
  if (parts.length === 0) return null
  return { parts }
}
