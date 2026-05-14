// faceNameStability.test.js — T7: sketch-edit stability for persistent face naming.
//
// Proves that the face-naming system keeps the correct face selected after an
// upstream sketch edit that renumbers positional face ids.
//
// The test simulates the scenario described in the design doc and the task spec:
//
//   1. Build Pad-A (rect sketch, 6 faces: TopCap, BottomCap, 4 Side.seg-N).
//   2. Record that a Fillet targets "Pad-A.TopCap".
//   3. "Edit" the sketch to add a stair-step (more segments → OCCT renumbers
//      all face indices: what was face 0 is now face 3, for example).
//   4. Re-evaluate face names for the new shape.
//   5. Assert that the fillet's stored face name "Pad-A.TopCap" still resolves
//      to the correct face (the index changed but the name is stable).
//
// Because the test runs in Node without OCCT WASM, we simulate the
// renumbering by hand:
//   - "Before edit": 6-face box, TopCap at index 0.
//   - "After edit":  the same box with the TopCap shuffled to index 3 (the
//     rest re-indexed too), representing what OCCT produces after adding two
//     more sketch segments.
//
// The key invariant: buildFaceNamesForExtrude produces "Pad-A.TopCap" for
// whichever face has the top-cap normal, regardless of its positional index.
// resolveFaceRef reads the stored name, finds the new index, and returns the
// correct face.
//
// No OCCT calls in this suite — all geometry is synthetic.

import { describe, it, expect } from 'vitest'
import { buildFaceNamesForExtrude } from '../lib/faceNaming.js'
import { resolveFaceRef } from '../lib/faceRef.js'

// ---------------------------------------------------------------------------
// Synthetic geometry helpers (mirrors faceNaming.test.js)
// ---------------------------------------------------------------------------

function makeFace(index, normal, sketchEntityId, sharedEdgeIndices, overrides = {}) {
  return {
    index,
    surfaceKind: 'plane',
    edgeCount: 4,
    edgeKinds: ['line', 'line', 'line', 'line'],
    vertexValences: [2, 2, 2, 2],
    normal,
    sharedEdgeIndices,
    sketchEntityId: sketchEntityId || null,
    isCap: false,
    isTop: false,
    ...overrides,
  }
}

/** Build the canonical 6-face rect box (TopCap first, then BottomCap, then sides). */
function makeRectBox6(topCapIndex = 0) {
  // Edges 0-3 for TopCap, 4-7 for BottomCap, unique pairs for sides.
  const offset = topCapIndex * 100  // separate edge pools to avoid adjacency bleed
  return [
    makeFace(topCapIndex,   [0, 0, 1],   null,    [offset + 0, offset + 1, offset + 2, offset + 3]),              // TopCap
    makeFace(topCapIndex + 1, [0, 0, -1], null,   [offset + 4, offset + 5, offset + 6, offset + 7]),              // BottomCap
    makeFace(topCapIndex + 2, [1, 0, 0],  'seg-0', [offset + 0, offset + 4, offset + 8, offset + 9]),
    makeFace(topCapIndex + 3, [-1, 0, 0], 'seg-1', [offset + 1, offset + 5, offset + 10, offset + 11]),
    makeFace(topCapIndex + 4, [0, 1, 0],  'seg-2', [offset + 2, offset + 6, offset + 12, offset + 13]),
    makeFace(topCapIndex + 5, [0, -1, 0], 'seg-3', [offset + 3, offset + 7, offset + 14, offset + 15]),
  ]
}

const Z_UP = [0, 0, 1]
const NODE_ID = 'Pad-A'

// ---------------------------------------------------------------------------
// Stub faceById: just returns the face descriptor at the requested index
// from the current face array.  In real OCCT this would return a TopoDS_Face;
// here we return the descriptor itself so we can check its index.
// ---------------------------------------------------------------------------
function makeFaceByIdStub(faces) {
  return (_oc, _shape, id) => {
    const f = faces.find((f) => f.index === id)
    return f != null ? f : null
  }
}

// ===========================================================================
// T7.1 — Names are stable after face renumbering
// ===========================================================================

describe('T7: face name stability after upstream sketch edit', () => {
  it('TopCap name resolves to the correct face even after positional renumbering', () => {
    // ---- Before edit: TopCap is at index 0 ----
    const facesBefore = makeRectBox6(0)
    const namesBefore = buildFaceNamesForExtrude(NODE_ID, facesBefore, Z_UP)

    // TopCap should be face 0, named "Pad-A.TopCap".
    expect(namesBefore['0']).toBe('Pad-A.TopCap')

    // Feature node from before the edit.
    const filletNode = {
      target_face_name: namesBefore['0'],  // "Pad-A.TopCap"
      target_face_id:   0,                 // legacy integer
    }

    // ---- After sketch edit: OCCT renumbers — TopCap is now at index 3 ----
    const facesAfter = makeRectBox6(3)   // TopCap at index 3, etc.
    const namesAfter = buildFaceNamesForExtrude(NODE_ID, facesAfter, Z_UP)

    // The new name map assigns "Pad-A.TopCap" to index 3.
    expect(namesAfter['3']).toBe('Pad-A.TopCap')
    // The old integer (0) now refers to the wrong face.
    expect(namesAfter['0']).not.toBe('Pad-A.TopCap')

    // resolveFaceRef with name-first logic should still find the correct face.
    const faceByIdAfter = makeFaceByIdStub(facesAfter)
    const resolved = resolveFaceRef(null, null, filletNode, namesAfter, faceByIdAfter)

    expect(resolved).not.toBeNull()
    expect(resolved.index).toBe(3)  // found by name, not by stale integer 0
  })

  it('falls back to integer when face name is absent (legacy file)', () => {
    const faces = makeRectBox6(0)
    const names = buildFaceNamesForExtrude(NODE_ID, faces, Z_UP)

    // Legacy node: no target_face_name.
    const legacyNode = { target_face_id: 0 }

    const faceById = makeFaceByIdStub(faces)
    const resolved = resolveFaceRef(null, null, legacyNode, names, faceById)

    expect(resolved).not.toBeNull()
    expect(resolved.index).toBe(0)
  })

  it('name miss falls through to integer fallback', () => {
    const faces = makeRectBox6(0)
    const names = buildFaceNamesForExtrude(NODE_ID, faces, Z_UP)

    // Node has a stale name that no longer exists, plus a valid integer.
    const staleNode = {
      target_face_name: 'OldFeature.SomeFace',  // stale — not in names
      target_face_id:   1,                       // valid legacy integer
    }

    const faceById = makeFaceByIdStub(faces)
    const resolved = resolveFaceRef(null, null, staleNode, names, faceById)

    expect(resolved).not.toBeNull()
    expect(resolved.index).toBe(1)   // fell back to integer
  })

  it('returns null when both name and integer are missing / invalid', () => {
    const faces = makeRectBox6(0)
    const names = buildFaceNamesForExtrude(NODE_ID, faces, Z_UP)
    const faceById = makeFaceByIdStub(faces)

    expect(resolveFaceRef(null, null, {}, names, faceById)).toBeNull()
    expect(resolveFaceRef(null, null, { target_face_id: -1 }, names, faceById)).toBeNull()
  })
})

// ===========================================================================
// T7.2 — push_pull face_name / face_id resolution
// ===========================================================================

describe('T7: push_pull node face resolution (face_name key)', () => {
  it('resolves push_pull by face_name', () => {
    const faces = makeRectBox6(2)   // TopCap at index 2
    const names = buildFaceNamesForExtrude(NODE_ID, faces, Z_UP)

    const ppNode = {
      face_name: 'Pad-A.TopCap',
      face_id:   99,  // stale integer — should be ignored
    }

    const faceById = makeFaceByIdStub(faces)
    const resolved = resolveFaceRef(null, null, ppNode, names, faceById, {
      nameKey: 'face_name',
      idKey:   'face_id',
    })

    expect(resolved).not.toBeNull()
    expect(resolved.index).toBe(2)  // found TopCap at the new index
  })
})

// ===========================================================================
// T7.3 — Carry-forward chain: Fillet after Pad preserves TopCap name
// ===========================================================================

import { nameOpOutput } from '../lib/faceNaming.js'

describe('T7: carry-forward chain stability (Fillet → Pad name survives)', () => {
  it('TopCap name from Pad survives through a subsequent Fillet op', () => {
    // After Pad: 6-face box.
    const padFaces = makeRectBox6(0)
    const padNames = buildFaceNamesForExtrude(NODE_ID, padFaces, Z_UP)

    // Fillet removes some edges; new fillet faces (indices 6, 7) appear.
    // All original faces are carried 1-to-1.
    const filletFaces = [
      ...padFaces,
      makeFace(6, [0.7, 0.7, 0], null, [50, 51, 52, 53], { surfaceKind: 'cylinder' }),
      makeFace(7, [-0.7, 0.7, 0], null, [54, 55, 56, 57], { surfaceKind: 'cylinder' }),
    ]
    const filletModMap = {
      modified: { 0: [0], 1: [1], 2: [2], 3: [3], 4: [4], 5: [5] },
      generated: [6, 7],
      deletedInputs: new Set(),
    }

    const namesAfterFillet = nameOpOutput('fillet', padNames, filletFaces, filletModMap, { nodeId: 'Fil-G' })

    // Pad-A.TopCap should have survived unchanged.
    expect(namesAfterFillet['0']).toBe('Pad-A.TopCap')

    // A node targeting "Pad-A.TopCap" should resolve correctly.
    const faceById = makeFaceByIdStub(filletFaces)
    const node = { target_face_name: 'Pad-A.TopCap', target_face_id: 0 }
    const resolved = resolveFaceRef(null, null, node, namesAfterFillet, faceById)

    expect(resolved).not.toBeNull()
    expect(resolved.index).toBe(0)
  })
})

// ===========================================================================
// T7.4 — Without persistent names, the stale-integer test would fail
// ===========================================================================

describe('T7: regression guard — stale integer targets wrong face', () => {
  it('demonstrates that integer-only lookup fails after renumbering', () => {
    const facesBefore = makeRectBox6(0)
    const namesBefore = buildFaceNamesForExtrude(NODE_ID, facesBefore, Z_UP)

    // Save the integer from the "before" state.
    const savedInteger = 0  // TopCap was at index 0
    expect(namesBefore[String(savedInteger)]).toBe('Pad-A.TopCap')

    // After edit: faces renumbered, TopCap is now at index 3.
    const facesAfter = makeRectBox6(3)
    const namesAfter = buildFaceNamesForExtrude(NODE_ID, facesAfter, Z_UP)

    // The saved integer 0 now points to a different face (not TopCap).
    expect(namesAfter[String(savedInteger)]).not.toBe('Pad-A.TopCap')

    // But the name still resolves to index 3.
    const faceById = makeFaceByIdStub(facesAfter)
    const nodeWithName = { target_face_name: 'Pad-A.TopCap', target_face_id: savedInteger }
    const resolved = resolveFaceRef(null, null, nodeWithName, namesAfter, faceById)

    expect(resolved).not.toBeNull()
    expect(resolved.index).toBe(3)   // correct: found by name
    expect(resolved.index).not.toBe(savedInteger)  // not the stale integer
  })
})
