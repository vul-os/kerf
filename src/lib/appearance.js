// Per-object appearance overrides for `.jscad` files.
//
// Stored as a single line comment at the very top of the source, in this
// exact format:
//
//   // kerf:appearance={"body":{"color":"#6b9bc9","opacity":0.45,"material":"6061-T6"}}
//
// Same trick as circuitMappings.js (see that file's rationale): the source is
// the artifact users version-control, JSCAD ignores comments, and round-tripping
// is a regex match/replace with no schema migration. The marker is recreated on
// every write, so it can't drift from the content.
//
// Only OVERRIDES live here — a part with no entry falls back to the palette
// colour the renderer assigns by index, so an untouched file stays free of the
// marker entirely.
//
// Hiding is deliberately NOT persisted. It matches the existing
// `hiddenPartIds` session state (workspace.js), and matches SolidWorks/Fusion,
// where show/hide is view state rather than a document property.

const MARKER = '// kerf:appearance='

// How far into the file we look for the marker. Generous enough to survive a
// user pasting a licence header above it.
const SCAN_LINES = 32

/** A part's appearance override. Every field is optional. */
export const APPEARANCE_FIELDS = ['color', 'opacity', 'material', 'metalness', 'roughness']

function clamp01(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return null
  return Math.min(1, Math.max(0, n))
}

// #rgb / #rrggbb (case-insensitive) → normalized '#rrggbb'. Anything else → null.
export function normalizeHex(value) {
  if (typeof value !== 'string') return null
  const m = /^#?([0-9a-f]{3}|[0-9a-f]{6})$/i.exec(value.trim())
  if (!m) return null
  let h = m[1].toLowerCase()
  if (h.length === 3) h = h[0] + h[0] + h[1] + h[1] + h[2] + h[2]
  return `#${h}`
}

/** '#rrggbb' → 0xRRGGBB, for THREE.Color / part.color. null on bad input. */
export function hexToInt(value) {
  const h = normalizeHex(value)
  return h == null ? null : parseInt(h.slice(1), 16)
}

/** 0xRRGGBB → '#rrggbb'. */
export function intToHex(n) {
  if (typeof n !== 'number' || !Number.isFinite(n)) return null
  const clamped = Math.min(0xffffff, Math.max(0, Math.round(n)))
  return `#${clamped.toString(16).padStart(6, '0')}`
}

// Drop unknown keys and coerce known ones. Returns null when nothing survives,
// so callers can delete the entry rather than persist `{}`.
function sanitizeEntry(raw) {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return null
  const out = {}

  const color = normalizeHex(raw.color)
  if (color) out.color = color

  const opacity = clamp01(raw.opacity)
  // 1 is the default — storing it is noise, and it lets "reset to opaque"
  // clear the entry instead of growing the marker.
  if (opacity != null && opacity < 1) out.opacity = opacity

  if (typeof raw.material === 'string' && raw.material.trim()) {
    out.material = raw.material.trim()
  }

  const metalness = clamp01(raw.metalness)
  if (metalness != null) out.metalness = metalness
  const roughness = clamp01(raw.roughness)
  if (roughness != null) out.roughness = roughness

  return Object.keys(out).length > 0 ? out : null
}

/**
 * Read the marker comment.
 *
 * @param   {string} content  the file source
 * @returns {Record<string, object>}  partId → appearance. `{}` when absent or
 *          malformed — never throws, so a hand-mangled marker degrades to
 *          "no overrides" rather than breaking the editor.
 */
export function parseAppearance(content) {
  if (typeof content !== 'string' || content.length === 0) return {}

  for (const line of content.split('\n', SCAN_LINES)) {
    const trimmed = line.trimStart()
    if (!trimmed.startsWith(MARKER)) continue

    try {
      const obj = JSON.parse(trimmed.slice(MARKER.length).trim())
      if (!obj || typeof obj !== 'object' || Array.isArray(obj)) return {}
      const out = {}
      for (const [partId, entry] of Object.entries(obj)) {
        const clean = sanitizeEntry(entry)
        if (clean) out[String(partId)] = clean
      }
      return out
    } catch {
      return {}
    }
  }
  return {}
}

/**
 * Replace (or insert, or remove) the marker comment.
 *
 * An empty override map clears the marker completely, so resetting every part
 * leaves the source exactly as it was before anyone touched appearance.
 *
 * @param   {string} content
 * @param   {Record<string, object>} appearance  partId → appearance
 * @returns {string} the updated source
 */
export function writeAppearance(content, appearance) {
  const safe = typeof content === 'string' ? content : ''
  const lines = safe.split('\n')

  let markerIdx = -1
  const scanLimit = Math.min(lines.length, SCAN_LINES)
  for (let i = 0; i < scanLimit; i++) {
    if (lines[i].trimStart().startsWith(MARKER)) {
      markerIdx = i
      break
    }
  }

  const cleaned = {}
  for (const [partId, entry] of Object.entries(appearance || {})) {
    const clean = sanitizeEntry(entry)
    if (clean) cleaned[String(partId)] = clean
  }

  // Nothing to store: drop the marker line if we have one.
  if (Object.keys(cleaned).length === 0) {
    if (markerIdx === -1) return safe
    lines.splice(markerIdx, 1)
    return lines.join('\n')
  }

  const markerLine = `${MARKER}${JSON.stringify(cleaned)}`
  if (markerIdx === -1) {
    lines.unshift(markerLine)
  } else {
    lines[markerIdx] = markerLine
  }
  return lines.join('\n')
}

/**
 * The source with the appearance marker removed.
 *
 * Used to decide whether a content change is *geometrically* meaningful: the
 * marker is a comment, so JSCAD's output cannot depend on it. Editing appearance
 * must not re-run the model (a re-run rebuilds every mesh, which flashes the
 * viewport), so the editor compares stripped sources and skips the run when only
 * the marker moved.
 */
export function stripAppearance(content) {
  if (typeof content !== 'string' || content.length === 0) return ''
  const lines = content.split('\n')
  const scanLimit = Math.min(lines.length, SCAN_LINES)
  for (let i = 0; i < scanLimit; i++) {
    if (lines[i].trimStart().startsWith(MARKER)) {
      lines.splice(i, 1)
      return lines.join('\n')
    }
  }
  return content
}

/**
 * Merge a patch into one part's entry, returning the whole map.
 *
 * A `null`/`undefined` field value CLEARS that field (that is how "reset
 * colour" is expressed), and an entry that ends up empty is dropped.
 */
export function mergeAppearance(appearance, partId, patch) {
  const id = String(partId)
  const next = { ...(appearance || {}) }
  const merged = { ...(next[id] || {}) }

  for (const [k, v] of Object.entries(patch || {})) {
    if (v == null) delete merged[k]
    else merged[k] = v
  }

  const clean = sanitizeEntry(merged)
  if (clean) next[id] = clean
  else delete next[id]
  return next
}
