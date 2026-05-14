// depGraph.test.js
//
// Tests for src/lib/depGraph.js — the project-wide reverse-dependency graph
// helpers that support cross-file invalidation of the sketch → jscad →
// assembly chain.
//
// Tests cover:
//   • buildSketchImports  — extracts sketch import paths from .jscad files
//   • buildAssemblyDeps   — extracts component file_ids from .assembly files
//   • dependentsOfSketch  — 0/1/N matches, multi-hop, self-referencing cycles

import { describe, it, expect, vi } from 'vitest'

// ---- Mock heavy deps that depGraph.js pulls in transitively ----------------

vi.mock('../lib/jscadRunner.js', async (importOriginal) => {
  const real = await importOriginal()
  return { ...real }
})

// assembly.js is a real module but it imports THREE — stub just the parse fn.
vi.mock('../lib/assembly.js', () => ({
  parseAssembly: (jsonStr) => {
    if (!jsonStr || !jsonStr.trim()) return { components: [], overrides: [] }
    try {
      const raw = JSON.parse(jsonStr)
      const components = (Array.isArray(raw?.components) ? raw.components : [])
        .filter((c) => c && (c.file_id || c.external_ref))
        .map((c) => ({ id: c.id || '', file_id: c.file_id || '', object_id: c.object_id || '' }))
      return { components, overrides: [] }
    } catch {
      return { components: [], overrides: [], _parseError: 'Invalid JSON' }
    }
  },
}))

import { buildSketchImports, buildAssemblyDeps, dependentsOfSketch } from '../lib/depGraph.js'

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeJscad(id, name, content, parentId = null) {
  return { id, name, kind: 'file', parent_id: parentId, content }
}
function makeAssembly(id, name, components = [], parentId = null) {
  return {
    id,
    name,
    kind: 'assembly',
    parent_id: parentId,
    content: JSON.stringify({ components }),
  }
}
function makeSketch(id, name, parentId = null) {
  return { id, name, kind: 'sketch', parent_id: parentId, content: '{}' }
}
function makeFolder(id, name, parentId = null) {
  return { id, name, kind: 'folder', parent_id: parentId }
}
function comp(id, fileId, objectId = 'body') {
  return { id, file_id: fileId, object_id: objectId }
}

// ---------------------------------------------------------------------------
// buildSketchImports
// ---------------------------------------------------------------------------
describe('buildSketchImports', () => {
  it('returns empty map for empty files array', () => {
    expect(buildSketchImports([])).toEqual(new Map())
  })

  it('returns empty map for non-array input', () => {
    expect(buildSketchImports(null)).toEqual(new Map())
    expect(buildSketchImports(undefined)).toEqual(new Map())
  })

  it('skips non-jscad files (sketches, folders, assemblies)', () => {
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeFolder('f1', 'parts'),
      makeAssembly('asm1', 'top.assembly'),
    ]
    expect(buildSketchImports(files)).toEqual(new Map())
  })

  it('skips jscad files with no content', () => {
    const files = [{ id: 'j1', name: 'b.jscad', kind: 'file', parent_id: null }]
    expect(buildSketchImports(files)).toEqual(new Map())
  })

  it('skips jscad files whose content has no sketch imports', () => {
    const files = [
      makeJscad('j1', 'b.jscad', `export default function () { return [] }`),
    ]
    expect(buildSketchImports(files)).toEqual(new Map())
  })

  it('returns a map entry for a jscad that imports one sketch', () => {
    const files = [
      makeJscad('j1', 'b.jscad', `import profile from '/parts/a.sketch'\nexport default function () { return [] }`),
    ]
    const result = buildSketchImports(files)
    expect(result.size).toBe(1)
    expect(result.get('j1')).toEqual(new Set(['/parts/a.sketch']))
  })

  it('collects multiple sketch imports from a single jscad', () => {
    const src = [
      `import p1 from '/parts/a.sketch'`,
      `import p2 from '/parts/b.sketch'`,
      `export default function () { return [] }`,
    ].join('\n')
    const files = [makeJscad('j1', 'b.jscad', src)]
    const result = buildSketchImports(files)
    expect(result.get('j1')).toEqual(new Set(['/parts/a.sketch', '/parts/b.sketch']))
  })

  it('handles double-quoted import paths', () => {
    const src = `import profile from "/parts/a.sketch"\nexport default function () { return [] }`
    const files = [makeJscad('j1', 'b.jscad', src)]
    const result = buildSketchImports(files)
    expect(result.get('j1')).toEqual(new Set(['/parts/a.sketch']))
  })

  it('normalises ./ relative paths to /abs form', () => {
    const src = `import profile from './parts/a.sketch'\nexport default function () { return [] }`
    const files = [makeJscad('j1', 'b.jscad', src)]
    const result = buildSketchImports(files)
    expect(result.get('j1')).toEqual(new Set(['/parts/a.sketch']))
  })

  it('handles a mixed file tree — only jscad files produce entries', () => {
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'b.jscad', `import p from '/a.sketch'`),
      makeAssembly('asm1', 'top.assembly', [comp('c1', 'j1')]),
      makeFolder('f1', 'parts'),
    ]
    const result = buildSketchImports(files)
    expect(result.size).toBe(1)
    expect(result.has('j1')).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// buildAssemblyDeps
// ---------------------------------------------------------------------------
describe('buildAssemblyDeps', () => {
  it('returns empty map for empty files array', () => {
    expect(buildAssemblyDeps([])).toEqual(new Map())
  })

  it('returns empty map for non-array input', () => {
    expect(buildAssemblyDeps(null)).toEqual(new Map())
  })

  it('skips non-assembly files', () => {
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'b.jscad', ''),
    ]
    expect(buildAssemblyDeps(files)).toEqual(new Map())
  })

  it('returns empty map when assembly has no content', () => {
    const files = [{ id: 'asm1', name: 'top.assembly', kind: 'assembly', parent_id: null }]
    expect(buildAssemblyDeps(files)).toEqual(new Map())
  })

  it('returns empty map when assembly has no components', () => {
    const files = [makeAssembly('asm1', 'top.assembly', [])]
    expect(buildAssemblyDeps(files)).toEqual(new Map())
  })

  it('returns correct component file_ids for an assembly', () => {
    const files = [
      makeAssembly('asm1', 'top.assembly', [
        comp('c1', 'j1'),
        comp('c2', 'j2'),
      ]),
    ]
    const result = buildAssemblyDeps(files)
    expect(result.size).toBe(1)
    expect(result.get('asm1')).toEqual(new Set(['j1', 'j2']))
  })

  it('deduplicates component file_ids (same jscad placed twice)', () => {
    const files = [
      makeAssembly('asm1', 'top.assembly', [
        comp('c1', 'j1', 'body'),
        comp('c2', 'j1', 'body'), // same jscad, second instance
      ]),
    ]
    const result = buildAssemblyDeps(files)
    expect(result.get('asm1')).toEqual(new Set(['j1']))
  })

  it('handles multiple assemblies independently', () => {
    const files = [
      makeAssembly('asm1', 'a.assembly', [comp('c1', 'j1')]),
      makeAssembly('asm2', 'b.assembly', [comp('c2', 'j2')]),
    ]
    const result = buildAssemblyDeps(files)
    expect(result.size).toBe(2)
    expect(result.get('asm1')).toEqual(new Set(['j1']))
    expect(result.get('asm2')).toEqual(new Set(['j2']))
  })
})

// ---------------------------------------------------------------------------
// dependentsOfSketch
// ---------------------------------------------------------------------------
describe('dependentsOfSketch', () => {
  it('returns empty lists when no files import the sketch (0 matches)', () => {
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'b.jscad', `export default function () { return [] }`),
    ]
    const result = dependentsOfSketch('/a.sketch', files)
    expect(result.jscads).toEqual([])
    expect(result.assemblies).toEqual([])
  })

  it('returns the matching jscad when 1 jscad imports the sketch', () => {
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'b.jscad', `import profile from '/a.sketch'`),
    ]
    const result = dependentsOfSketch('/a.sketch', files)
    expect(result.jscads).toContain('j1')
    expect(result.assemblies).toEqual([])
  })

  it('returns N jscads when N jscad files all import the sketch', () => {
    const src = (path) => `import profile from '${path}'\nexport default function () { return [] }`
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'part1.jscad', src('/a.sketch')),
      makeJscad('j2', 'part2.jscad', src('/a.sketch')),
      makeJscad('j3', 'other.jscad', src('/other.sketch')),
    ]
    const result = dependentsOfSketch('/a.sketch', files)
    expect(result.jscads).toHaveLength(2)
    expect(result.jscads).toContain('j1')
    expect(result.jscads).toContain('j2')
    expect(result.jscads).not.toContain('j3')
  })

  it('returns empty jscads/assemblies for null / missing inputs', () => {
    const out1 = dependentsOfSketch(null, [])
    expect(out1.jscads).toEqual([])
    expect(out1.assemblies).toEqual([])

    const out2 = dependentsOfSketch('/a.sketch', null)
    expect(out2.jscads).toEqual([])
    expect(out2.assemblies).toEqual([])
  })

  // -------------------------------------------------------------------------
  // Multi-hop: sketch → 2 jscads → 3 assemblies
  // -------------------------------------------------------------------------
  it('multi-hop: sketch → 2 jscads → 3 assemblies (each assembly refs 1 of the 2 jscads)', () => {
    //   /a.sketch
    //     ↓ imported by
    //   j1 (part1.jscad) ← referenced by asm1, asm2
    //   j2 (part2.jscad) ← referenced by asm3
    //   j3 (part3.jscad) ← does NOT import /a.sketch → not in dep set
    const src = (path) => `import profile from '${path}'\nexport default function () { return [] }`
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'part1.jscad', src('/a.sketch')),
      makeJscad('j2', 'part2.jscad', src('/a.sketch')),
      makeJscad('j3', 'part3.jscad', src('/other.sketch')),
      makeAssembly('asm1', 'assembly1.assembly', [comp('c1', 'j1')]),
      makeAssembly('asm2', 'assembly2.assembly', [comp('c2', 'j1'), comp('c3', 'j3')]),
      makeAssembly('asm3', 'assembly3.assembly', [comp('c4', 'j2')]),
    ]

    const result = dependentsOfSketch('/a.sketch', files)

    expect(result.jscads).toHaveLength(2)
    expect(result.jscads).toContain('j1')
    expect(result.jscads).toContain('j2')
    expect(result.jscads).not.toContain('j3')

    expect(result.assemblies).toHaveLength(3)
    expect(result.assemblies).toContain('asm1')
    expect(result.assemblies).toContain('asm2')
    expect(result.assemblies).toContain('asm3')
  })

  it('multi-hop: assembly that references ONLY unaffected jscad is NOT included', () => {
    const src = (path) => `import profile from '${path}'\nexport default function () { return [] }`
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'part1.jscad', src('/a.sketch')),
      makeJscad('j2', 'part2.jscad', src('/other.sketch')), // not affected
      makeAssembly('asm1', 'assembly1.assembly', [comp('c1', 'j1')]), // affected
      makeAssembly('asm2', 'assembly2.assembly', [comp('c2', 'j2')]), // not affected
    ]

    const result = dependentsOfSketch('/a.sketch', files)
    expect(result.assemblies).toContain('asm1')
    expect(result.assemblies).not.toContain('asm2')
  })

  // -------------------------------------------------------------------------
  // Cycle handling: assembly that references itself
  // -------------------------------------------------------------------------
  it('cycle: assembly self-reference does not cause infinite loop', () => {
    // An assembly that lists itself as a component is malformed data, but
    // the graph walk must terminate. The self-referencing assembly can only
    // be included if it also references an affected jscad (which it doesn't
    // here — it's its own only component).
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'part.jscad', `import p from '/a.sketch'`),
      makeAssembly('asm-self', 'self.assembly', [
        comp('c1', 'j1'),       // this makes asm-self affected
        comp('c2', 'asm-self'), // self-reference — must not cause a loop
      ]),
    ]
    // Should complete without hanging and include asm-self (because of j1).
    const result = dependentsOfSketch('/a.sketch', files)
    expect(result.jscads).toContain('j1')
    expect(result.assemblies).toContain('asm-self')
  })

  it('cycle: two assemblies referencing each other do not cause infinite loop', () => {
    // Neither of them references an affected jscad, so neither should appear.
    const files = [
      makeSketch('s1', 'a.sketch'),
      makeJscad('j1', 'part.jscad', `import p from '/other.sketch'`), // not affected
      makeAssembly('asm1', 'a.assembly', [comp('c1', 'asm2')]),
      makeAssembly('asm2', 'b.assembly', [comp('c2', 'asm1')]),
    ]
    const result = dependentsOfSketch('/a.sketch', files)
    expect(result.jscads).toEqual([])
    expect(result.assemblies).toEqual([])
  })
})
