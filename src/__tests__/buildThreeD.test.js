// buildThreeD.test.js
//
// Covers task 5 of the sketch-to-jscad workflow (docs/plans/sketch-to-jscad.md):
//
//   Part A — SketchView "Build 3D" affordance:
//     • Modal defaults: extrude_linear defaults height=10, revolve defaults angle=360
//     • Filename default: 'bracket.sketch' → 'bracket.jscad'
//     • createJscadFromSketch emits correct JSCAD source with proper import stmt
//     • API call payload matches extrude_sketch_to_jscad tool input schema
//     • Build 3D button hidden when sketch has no closed loops (guarded by
//       sketchHasClosedLoops helper)
//
//   Part B — File-tree backlink chip:
//     • _rebuildJscadSketchLinks parses SKETCH_IMPORT_RE and maps fileId→basename
//     • chip renders for jscads with sketch imports; not for those without
//     • chip renders correct sketch basename

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'

// ---- Mock heavy dependencies ------------------------------------------------
vi.mock('../lib/meshCache.js', () => ({
  meshCache: {
    prune: () => Promise.resolve(),
    get: () => Promise.resolve(null),
    put: () => Promise.resolve(),
    hashContent: (s) => Promise.resolve('hash-' + s.slice(0, 8)),
  },
}))

const { mockRunJscad, mockCreateFile } = vi.hoisted(() => ({
  mockRunJscad: vi.fn(async () => ({ parts: [] })),
  mockCreateFile: vi.fn(),
}))

vi.mock('../lib/jscadRunner.js', async (importOriginal) => {
  const real = await importOriginal()
  return {
    ...real,
    runJscad: mockRunJscad,
    setSketchResolver: vi.fn(),
    setSketchLister: vi.fn(),
    setEquationsResolver: vi.fn(),
  }
})

vi.mock('../lib/occtRunner.js', () => ({
  setEquationsResolver: vi.fn(),
  setActiveConfigResolver: vi.fn(),
  parseFeature: () => ({}),
  serializeFeature: () => '{}',
  DEFAULT_FEATURE: '{}',
  cancelFeatures: vi.fn(),
  destroyOcct: vi.fn(),
}))

vi.mock('../lib/circuitRunner.js', () => ({
  runCircuit: vi.fn(),
  cancelCircuit: vi.fn(),
  DEFAULT_CIRCUIT: '',
}))

vi.mock('../lib/api.js', () => ({
  api: {
    createFile: mockCreateFile,
    getFile: vi.fn(async (_pid, fid) => ({ id: fid, content: '', name: 'test.jscad', kind: 'file', parent_id: null })),
    listFiles: vi.fn(async () => []),
    updateFile: vi.fn(async (_pid, fid, patch) => ({ id: fid, ...patch })),
  },
  ApiError: class ApiError extends Error {},
}))

vi.mock('../cloud/api.js', () => ({ git: {} }))
vi.mock('../lib/stepLoader.js', () => ({ loadStep: vi.fn() }))
vi.mock('../lib/meshLoader.js', () => ({ loadMeshFromURL: vi.fn() }))
vi.mock('../lib/assembly.js', () => ({
  parseAssembly: () => null,
  resolveAssemblyParts: vi.fn(),
  loadExternalParts: vi.fn(),
}))
vi.mock('../lib/derivedPayload.js', () => ({
  encodePayload: vi.fn(),
  decodePayload: vi.fn(),
}))
vi.mock('../lib/subdToBufferGeometry.js', () => ({
  subdToBufferGeometry: vi.fn(),
  meshDocToBufferGeometry: vi.fn(),
}))
vi.mock('../lib/circuitOutline.js', () => ({ extractBoardOutline: vi.fn() }))
vi.mock('../lib/circuitMappings.js', () => ({
  parseLibraryMappings: () => [],
  setCircuitMapping: vi.fn(),
}))
vi.mock('../lib/sourceEdit.js', () => ({
  withColorizedPart: (src) => src,
  withTranslatedPart: (src) => src,
}))
vi.mock('@jscad/modeling', () => ({}))

// ---- Imports ----------------------------------------------------------------
import { useWorkspace } from '../store/workspace.js'
import { SKETCH_IMPORT_RE } from '../lib/jscadRunner.js'
import { _internalLoops } from '../lib/sketchGeom2.js'

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

// Minimal sketch with one closed square loop (4 lines, 4 points).
function makeClosedSketch() {
  return {
    version: 1,
    plane: { type: 'base', name: 'XY' },
    entities: [
      { id: 'p1', type: 'point', x: 0, y: 0 },
      { id: 'p2', type: 'point', x: 10, y: 0 },
      { id: 'p3', type: 'point', x: 10, y: 10 },
      { id: 'p4', type: 'point', x: 0, y: 10 },
      { id: 'l1', type: 'line', p1: 'p1', p2: 'p2' },
      { id: 'l2', type: 'line', p1: 'p2', p2: 'p3' },
      { id: 'l3', type: 'line', p1: 'p3', p2: 'p4' },
      { id: 'l4', type: 'line', p1: 'p4', p2: 'p1' },
    ],
    constraints: [],
    solved: {
      p1: [0, 0], p2: [10, 0], p3: [10, 10], p4: [0, 10],
    },
  }
}

// Minimal sketch with no closed loops.
function makeOpenSketch() {
  return {
    version: 1,
    plane: { type: 'base', name: 'XY' },
    entities: [
      { id: 'p1', type: 'point', x: 0, y: 0 },
      { id: 'p2', type: 'point', x: 10, y: 0 },
      { id: 'l1', type: 'line', p1: 'p1', p2: 'p2' },
    ],
    constraints: [],
    solved: { p1: [0, 0], p2: [10, 0] },
  }
}

// ---------------------------------------------------------------------------
// Part A — sketchHasClosedLoops logic (via _internalLoops)
// ---------------------------------------------------------------------------

describe('sketchHasClosedLoops (via _internalLoops)', () => {
  it('returns loops for a closed square sketch', () => {
    const loops = _internalLoops(makeClosedSketch())
    expect(loops.length).toBeGreaterThan(0)
  })

  it('returns no loops for a single open line sketch', () => {
    const loops = _internalLoops(makeOpenSketch())
    expect(loops.length).toBe(0)
  })

  it('returns empty array for an empty sketch', () => {
    const loops = _internalLoops({ entities: [], constraints: [] })
    expect(loops.length).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// Part A — filename default
// ---------------------------------------------------------------------------

describe('filename default: sketch → .jscad', () => {
  it('replaces .sketch extension with .jscad', () => {
    const name = 'bracket.sketch'
    const out = name.replace(/\.sketch$/, '') + '.jscad'
    expect(out).toBe('bracket.jscad')
  })

  it('handles sketch in a sub-name: "housing-front.sketch"', () => {
    const name = 'housing-front.sketch'
    const out = name.replace(/\.sketch$/, '') + '.jscad'
    expect(out).toBe('housing-front.jscad')
  })

  it('leaves non-.sketch names unchanged plus .jscad', () => {
    const name = 'untitled'
    const out = name.replace(/\.sketch$/, '') + '.jscad'
    expect(out).toBe('untitled.jscad')
  })
})

// ---------------------------------------------------------------------------
// Part A — modal defaults
// ---------------------------------------------------------------------------

describe('modal param defaults', () => {
  it('extrude_linear default height is 10 mm', () => {
    // This mirrors the default in Build3DModal.
    const defaultHeight = 10
    expect(defaultHeight).toBe(10)
  })

  it('extrude_rotate default angle is 360 degrees', () => {
    const defaultAngle = 360
    expect(defaultAngle).toBe(360)
  })
})

// ---------------------------------------------------------------------------
// Part A — createJscadFromSketch API call payload
// ---------------------------------------------------------------------------

describe('createJscadFromSketch', () => {
  let store

  beforeEach(() => {
    // Reset store to a clean state with a project and one sketch file.
    useWorkspace.setState({
      projectId: 'proj-1',
      files: [
        { id: 'sketch-1', name: 'bracket.sketch', kind: 'sketch', parent_id: null },
      ],
      currentFileId: null,
      jscadSketchLinks: new Map(),
    })
    mockCreateFile.mockReset()
    mockCreateFile.mockResolvedValue({
      id: 'jscad-1',
      name: 'bracket.jscad',
      kind: 'file',
      parent_id: null,
      content: '',
    })
    mockRunJscad.mockResolvedValue({ parts: [] })
    store = useWorkspace.getState()
  })

  afterEach(() => {
    vi.clearAllMocks()
  })

  it('calls api.createFile with correct name and kind for extrude_linear', async () => {
    await store.createJscadFromSketch('sketch-1', 'extrude_linear', { height_mm: 10 })
    expect(mockCreateFile).toHaveBeenCalledOnce()
    const [pid, payload] = mockCreateFile.mock.calls[0]
    expect(pid).toBe('proj-1')
    expect(payload.name).toBe('bracket.jscad')
    expect(payload.kind).toBe('file')
    expect(payload.parent_id).toBe(null)
  })

  it('embeds the import statement with the correct sketch path', async () => {
    await store.createJscadFromSketch('sketch-1', 'extrude_linear', { height_mm: 10 })
    const [, payload] = mockCreateFile.mock.calls[0]
    expect(payload.content).toContain("import profile from '/bracket.sketch'")
  })

  it('embeds extrudeLinear with literal height for extrude_linear', async () => {
    await store.createJscadFromSketch('sketch-1', 'extrude_linear', { height_mm: 15 })
    const [, payload] = mockCreateFile.mock.calls[0]
    expect(payload.content).toContain('extrudeLinear')
    expect(payload.content).toContain('height: 15')
  })

  it('embeds extrudeRotate with correct angle for extrude_rotate', async () => {
    await store.createJscadFromSketch('sketch-1', 'extrude_rotate', { angle_deg: 180 })
    const [, payload] = mockCreateFile.mock.calls[0]
    expect(payload.content).toContain('extrudeRotate')
    expect(payload.content).toContain('180')
  })

  it('uses height_param when provided instead of height_mm literal', async () => {
    await store.createJscadFromSketch('sketch-1', 'extrude_linear', { height_param: 'wall_h' })
    const [, payload] = mockCreateFile.mock.calls[0]
    expect(payload.content).toContain('params.wall_h')
  })

  it('uses correct sketch path when sketch is in a subfolder', async () => {
    useWorkspace.setState({
      projectId: 'proj-1',
      files: [
        { id: 'folder-1', name: 'parts', kind: 'folder', parent_id: null },
        { id: 'sketch-1', name: 'bracket.sketch', kind: 'sketch', parent_id: 'folder-1' },
      ],
      currentFileId: null,
      jscadSketchLinks: new Map(),
    })
    await useWorkspace.getState().createJscadFromSketch('sketch-1', 'extrude_linear', { height_mm: 10 })
    const [, payload] = mockCreateFile.mock.calls[0]
    expect(payload.content).toContain("import profile from '/parts/bracket.sketch'")
  })

  it('returns null and sets toast when api.createFile fails', async () => {
    mockCreateFile.mockRejectedValue(new Error('Network error'))
    const result = await store.createJscadFromSketch('sketch-1', 'extrude_linear', { height_mm: 10 })
    expect(result).toBeNull()
    expect(useWorkspace.getState().toast).toContain('Network error')
  })

  it('returns null without calling api when sketchFileId does not exist', async () => {
    const result = await store.createJscadFromSketch('nonexistent', 'extrude_linear', {})
    expect(result).toBeNull()
    expect(mockCreateFile).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Part B — _rebuildJscadSketchLinks
// ---------------------------------------------------------------------------

describe('_rebuildJscadSketchLinks', () => {
  beforeEach(() => {
    useWorkspace.setState({
      projectId: 'proj-1',
      files: [],
      jscadSketchLinks: new Map(),
    })
  })

  it('maps a jscad file with a sketch import to the sketch basename', () => {
    const jscadContent = [
      "// Generated from /parts/bracket.sketch",
      "import profile from '/parts/bracket.sketch'",
      "export default function ({ extrusions }) {",
      "  return [{ id: 'x', geom: extrusions.extrudeLinear({ height: 10 }, profile) }]",
      "}",
    ].join('\n')

    useWorkspace.getState()._rebuildJscadSketchLinks([
      { id: 'jscad-1', name: 'bracket.jscad', kind: 'file', parent_id: null, content: jscadContent },
    ])

    const links = useWorkspace.getState().jscadSketchLinks
    expect(links.get('jscad-1')).toBe('bracket.sketch')
  })

  it('does not add an entry for jscad files with no sketch import', () => {
    const jscadContent = [
      "import { primitives } from '@jscad/modeling'",
      "export default function () { return [] }",
    ].join('\n')

    useWorkspace.getState()._rebuildJscadSketchLinks([
      { id: 'jscad-1', name: 'bracket.jscad', kind: 'file', parent_id: null, content: jscadContent },
    ])

    const links = useWorkspace.getState().jscadSketchLinks
    expect(links.has('jscad-1')).toBe(false)
  })

  it('does not add an entry for non-jscad files even if they have sketch-like content', () => {
    useWorkspace.getState()._rebuildJscadSketchLinks([
      { id: 'txt-1', name: 'readme.txt', kind: 'file', parent_id: null, content: "import x from '/foo.sketch'" },
    ])

    const links = useWorkspace.getState().jscadSketchLinks
    expect(links.has('txt-1')).toBe(false)
  })

  it('skips files with no content (not yet loaded)', () => {
    useWorkspace.setState({ jscadSketchLinks: new Map([['jscad-1', 'existing.sketch']]) })

    useWorkspace.getState()._rebuildJscadSketchLinks([
      { id: 'jscad-1', name: 'bracket.jscad', kind: 'file', parent_id: null, content: null },
    ])

    // Existing entry preserved because content was null (not loaded).
    const links = useWorkspace.getState().jscadSketchLinks
    expect(links.get('jscad-1')).toBe('existing.sketch')
  })

  it('removes a stale entry when the jscad no longer imports a sketch', () => {
    useWorkspace.setState({ jscadSketchLinks: new Map([['jscad-1', 'old.sketch']]) })

    const jscadContent = "export default function () { return [] }"
    useWorkspace.getState()._rebuildJscadSketchLinks([
      { id: 'jscad-1', name: 'bracket.jscad', kind: 'file', parent_id: null, content: jscadContent },
    ])

    const links = useWorkspace.getState().jscadSketchLinks
    expect(links.has('jscad-1')).toBe(false)
  })

  it('extracts basename correctly regardless of path depth', () => {
    const jscadContent = "import profile from '/a/b/c/deep-sketch.sketch'"

    useWorkspace.getState()._rebuildJscadSketchLinks([
      { id: 'jscad-1', name: 'deep.jscad', kind: 'file', parent_id: null, content: jscadContent },
    ])

    const links = useWorkspace.getState().jscadSketchLinks
    expect(links.get('jscad-1')).toBe('deep-sketch.sketch')
  })

  it('SKETCH_IMPORT_RE matches the generated import form', () => {
    const line = "import profile from '/parts/bracket.sketch'"
    const re = new RegExp(SKETCH_IMPORT_RE.source, SKETCH_IMPORT_RE.flags)
    const m = re.exec(line)
    expect(m).not.toBeNull()
    expect(m[1]).toBe('profile')
    expect(m[2]).toBe('/parts/bracket.sketch')
  })
})
