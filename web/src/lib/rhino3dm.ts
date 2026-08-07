/**
 * rhino3dm.js — Pure-JS helpers for Rhino .3dm file handling.
 *
 * is3dmFile(filename)          → bool
 * splitImported3dmTree(files)  → { folder_layout }
 *
 * No side-effects; no DOM dependencies. Suitable for use in both the
 * main thread and Web Workers.
 */

// ── Extension detection ────────────────────────────────────────────────────

/**
 * Returns true if `filename` ends with ".3dm" (case-insensitive).
 * @param {string} filename
 * @returns {boolean}
 */
export function is3dmFile(filename) {
  if (typeof filename !== 'string' || filename.length === 0) return false
  return filename.toLowerCase().endsWith('.3dm')
}

// ── Kind → project tree extension ─────────────────────────────────────────

const KIND_EXT = {
  feature: '.feature',
  sketch: '.sketch',
  surf: '.surf',
  mesh: '.mesh',
  point: '.point',
  instance: '.json',
  file: '',
}

function extForKind(kind) {
  return KIND_EXT[kind] ?? ''
}

// ── Tree layout proposal ───────────────────────────────────────────────────

/**
 * Given an array of imported file descriptors (as returned by pyworker's
 * /import-3dm response), proposes a folder layout grouped by Rhino layer.
 *
 * Each element in `files_array` is expected to have at minimum:
 *   { name: string, kind: string, content?: { rhino_layer?: string } }
 *
 * Returns:
 * {
 *   folder_layout: {
 *     [layerName: string]: Array<{ name, kind, path }>
 *   }
 * }
 *
 * Files without a rhino_layer are placed in the special "_ungrouped" bucket.
 *
 * @param {Array<{name: string, kind: string, content?: object}>} files_array
 * @returns {{ folder_layout: Record<string, Array<{name: string, kind: string, path: string}>> }}
 */
export function splitImported3dmTree(files_array) {
  if (!Array.isArray(files_array)) {
    return { folder_layout: {} }
  }

  /** @type {Record<string, Array<{name: string, kind: string, path: string}>>} */
  const folder_layout = {}

  for (const f of files_array) {
    if (!f || typeof f !== 'object') continue

    const rawName = typeof f.name === 'string' ? f.name : 'unnamed'
    const kind = typeof f.kind === 'string' ? f.kind : 'file'

    // Determine the layer / folder this object belongs to
    const layerName =
      (typeof f.content === 'object' && f.content !== null && typeof f.content.rhino_layer === 'string')
        ? f.content.rhino_layer.trim() || '_ungrouped'
        : '_ungrouped'

    // Sanitise: replace path separators and leading dots
    const safeLayer = layerName.replace(/[/\\]/g, '_').replace(/^\.+/, '')

    // Build the proposed path within the import folder
    // Strip any existing extension then add the canonical Kerf one
    const baseName = rawName.replace(/\.[^.]*$/, '')
    const ext = extForKind(kind)
    const leafName = baseName + ext
    const path = `/${safeLayer}/${leafName}`

    if (!folder_layout[safeLayer]) {
      folder_layout[safeLayer] = []
    }
    folder_layout[safeLayer].push({ name: leafName, kind, path })
  }

  return { folder_layout }
}
