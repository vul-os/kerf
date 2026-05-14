// faceRef.js — T4: resolveFaceRef — name-first face lookup with integer fallback.
//
// Used by op handlers in occtWorker.js (push_pull, cut_from_sketch,
// boss_with_draft, fillet, chamfer) when they need to identify a face on
// the current shape.
//
// Resolution order (matches plan doc §"Resolution order (worker)"):
//   1. If `target_face_name` (or `face_name`) is set and the name exists in
//      `faceNames` → return faceById(oc, shape, <that index>).
//   2. Else if `target_face_id` (or `face_id`) is a non-negative integer →
//      return faceById(oc, shape, id).
//   3. Else → return null.
//
// `faceNames` is the Record<string,string> emitted by the worker's
// currentFaceNamer closure (faceIndex-as-string → name-string).
// Callers pass the CURRENT namer's output, not a stale snapshot.
//
// No OCCT coupling in this module — `faceById` is injected by the caller so
// this file can be unit-tested in vitest without OCCT WASM.

/**
 * Resolve a face reference from a feature node against the current shape.
 *
 * @param {object} oc        - OCCT handle (passed through to faceByIdFn)
 * @param {object} shape     - Current TopoDS_Shape
 * @param {object} node      - Feature node object (may have target_face_name /
 *                             face_name and/or target_face_id / face_id)
 * @param {Record<string,string>} faceNames
 *                           - faceIndex(string) → name(string) from the worker
 *                             namer closure. Pass {} or null when unavailable.
 * @param {function}         faceByIdFn
 *                           - (oc, shape, id: number) → TopoDS_Face | null
 * @param {object}           [opts]
 * @param {string}           [opts.nameKey='target_face_name']
 *                           - Node property to read the persistent name from.
 *                             Pass 'face_name' for push_pull nodes.
 * @param {string}           [opts.idKey='target_face_id']
 *                           - Node property to read the integer id from.
 *                             Pass 'face_id' for push_pull nodes.
 * @returns {TopoDS_Face | null}
 */
export function resolveFaceRef(oc, shape, node, faceNames, faceByIdFn, opts = {}) {
  const nameKey = opts.nameKey || 'target_face_name'
  const idKey   = opts.idKey   || 'target_face_id'

  const names = faceNames || {}

  // 1. Name-first: search the faceNames map for a matching name string.
  const wantName = node[nameKey]
  if (wantName && typeof wantName === 'string' && wantName.trim()) {
    const trimmed = wantName.trim()
    for (const [idxStr, n] of Object.entries(names)) {
      if (n === trimmed) {
        const idx = Number(idxStr)
        if (Number.isFinite(idx) && idx >= 0) {
          const face = faceByIdFn(oc, shape, idx)
          if (face != null) return face
        }
        break // name matched but lookup failed — fall through to integer
      }
    }
    // Name miss — fall through to integer fallback.
  }

  // 2. Integer fallback.
  const rawId = node[idKey]
  if (rawId != null) {
    const id = Number(rawId)
    if (Number.isFinite(id) && id >= 0) {
      return faceByIdFn(oc, shape, id)
    }
  }

  return null
}

/**
 * Convenience wrapper: extract current faceNames from a namer closure and
 * call resolveFaceRef.
 *
 * When `currentFaceNamer` is null (no namer attached yet, e.g. the op precedes
 * any face-emitting op), we fall back to the integer id path only.
 *
 * @param {object}              oc
 * @param {object}              shape
 * @param {object}              node
 * @param {function|null}       currentFaceNamer  - (oc, shape) → Record<string,string>
 * @param {function}            faceByIdFn
 * @param {object}              [opts]
 * @returns {TopoDS_Face | null}
 */
export function resolveFaceRefWithNamer(oc, shape, node, currentFaceNamer, faceByIdFn, opts = {}) {
  let faceNames = {}
  if (typeof currentFaceNamer === 'function') {
    try {
      faceNames = currentFaceNamer(oc, shape) || {}
    } catch {
      faceNames = {}
    }
  }
  return resolveFaceRef(oc, shape, node, faceNames, faceByIdFn, opts)
}
