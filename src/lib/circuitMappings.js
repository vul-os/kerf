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

const MARKER = '// kerf:library-mappings='

// parseLibraryMappings reads the marker comment and returns a refdes → file_id
// map. Missing or malformed → empty object (never throws).
export function parseLibraryMappings(content) {
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
      const obj = JSON.parse(json)
      if (obj && typeof obj === 'object' && !Array.isArray(obj)) {
        const out = {}
        for (const [k, v] of Object.entries(obj)) {
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
export function writeLibraryMappings(content, mappings) {
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
export function setCircuitMapping(content, refdes, partFileId) {
  const cur = parseLibraryMappings(content)
  if (partFileId) cur[refdes] = partFileId
  else delete cur[refdes]
  return { mappings: cur, content: writeLibraryMappings(content, cur) }
}
