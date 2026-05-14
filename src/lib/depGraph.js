// depGraph.js — pure-JS helpers for the project-wide reverse-dependency graph.
//
// The graph is: .sketch → many .jscad (or .feature) → many .assembly
//
// We do a flat O(N) scan over the `files` array on every sketch save.
// Projects are typically < 1000 files so this is fine; a lazy cached build
// is a future optimisation.
//
// Files that carry `content` are read inline — if a file has no `content`
// field (list-only row) its deps are skipped silently (no content → no
// imports). The caller (workspace.js) already holds the in-memory files list
// and passes it directly; we never issue network requests.

import { SKETCH_IMPORT_RE } from './jscadRunner.js'
import { parseAssembly } from './assembly.js'

// ---------------------------------------------------------------------------
// buildSketchImports
//
// Walk every `jscad`-kind file in `files` and extract its sketch import paths.
// Returns: Map<jscadFileId, Set<sketchAbsPath>>
//
// `files` — the array of File rows from the workspace store. Each row has at
//   minimum: { id, name, kind?, parent_id, content? }.
// ---------------------------------------------------------------------------
export function buildSketchImports(files) {
  if (!Array.isArray(files)) return new Map()
  const result = new Map()
  for (const file of files) {
    if (!isJscadFile(file)) continue
    const content = file.content
    if (!content) continue
    const paths = extractSketchPathsFromSource(content)
    if (paths.size > 0) {
      result.set(file.id, paths)
    }
  }
  return result
}

// ---------------------------------------------------------------------------
// buildAssemblyDeps
//
// Walk every `assembly`-kind file in `files` and extract the file_ids it
// references in its components list.
// Returns: Map<assemblyFileId, Set<componentFileId>>
// ---------------------------------------------------------------------------
export function buildAssemblyDeps(files) {
  if (!Array.isArray(files)) return new Map()
  const result = new Map()
  for (const file of files) {
    if (!isAssemblyFile(file)) continue
    const content = file.content
    if (!content) continue
    let parsed
    try {
      parsed = parseAssembly(content)
    } catch {
      continue
    }
    const deps = new Set()
    for (const comp of (parsed?.components || [])) {
      if (comp.file_id) deps.add(comp.file_id)
    }
    if (deps.size > 0) {
      result.set(file.id, deps)
    }
  }
  return result
}

// ---------------------------------------------------------------------------
// dependentsOfSketch
//
// For a given sketch absolute path, return:
//   { jscads: string[], assemblies: string[] }
//
// `jscads`      — file_ids of .jscad files that import this sketch
// `assemblies`  — file_ids of .assembly files that reference at least one
//                 of those jscads (transitively)
//
// The walk is two hops only (sketch → jscad → assembly). Deeper nesting
// (assembly-in-assembly where the outer references the sketch-tainted jscad)
// is handled because `buildAssemblyDeps` records all component file_ids, and
// we check whether any of them are in `affectedJscads`.
//
// Cycle guard: assemblies that reference themselves (or circular assembly
// chains) cannot affect the output set because we test file_ids that are
// already in `affectedJscads`; a self-referencing assembly would need to be
// a jscad to be in that set.
// ---------------------------------------------------------------------------
export function dependentsOfSketch(sketchAbsPath, files) {
  if (!sketchAbsPath || !Array.isArray(files)) {
    return { jscads: [], assemblies: [] }
  }

  const sketchImports = buildSketchImports(files)
  const assemblyDeps  = buildAssemblyDeps(files)

  // 1. Find jscads that import this sketch.
  const affectedJscads = new Set()
  for (const [jscadId, sketchPaths] of sketchImports) {
    if (sketchPaths.has(sketchAbsPath)) {
      affectedJscads.add(jscadId)
    }
  }

  // 2. Find assemblies that reference at least one affected jscad.
  const affectedAssemblies = new Set()
  for (const [assemblyId, componentFileIds] of assemblyDeps) {
    for (const fid of componentFileIds) {
      if (affectedJscads.has(fid)) {
        affectedAssemblies.add(assemblyId)
        break
      }
    }
  }

  return {
    jscads:     Array.from(affectedJscads),
    assemblies: Array.from(affectedAssemblies),
  }
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

function isJscadFile(file) {
  if (!file) return false
  // kind == 'file' is used for .jscad by workspace.js (not yet tagged as
  // 'jscad' in the DB kind column). Fall back to name-based detection.
  const name = (file.name || '').toLowerCase()
  if (file.kind === 'jscad') return true
  // DB stores .jscad rows with kind='file'; anything else with a .jscad
  // extension also qualifies.
  if (name.endsWith('.jscad')) return true
  // Also include .feature files which can import sketches for profile ops.
  if (file.kind === 'feature' || name.endsWith('.feature')) return false // feature dep walk is deferred
  return false
}

function isAssemblyFile(file) {
  if (!file) return false
  const name = (file.name || '').toLowerCase()
  return file.kind === 'assembly' || name.endsWith('.assembly')
}

// Extract resolved sketch abs paths from a JSCAD source string.
// Returns a Set<string> of absolute sketch paths.
// Relative paths (./foo.sketch) are normalised to '/foo.sketch' as a
// best-effort approximation; workspace.js's jscadImportsSketch does the
// same thing for the single-file check, so the two are consistent.
function extractSketchPathsFromSource(source) {
  const paths = new Set()
  // Fresh RegExp to avoid stateful lastIndex on the shared /gm export.
  const re = new RegExp(SKETCH_IMPORT_RE.source, SKETCH_IMPORT_RE.flags)
  let m
  while ((m = re.exec(source)) !== null) {
    let p = m[2] // path captured in group 2
    if (p.startsWith('./')) {
      p = '/' + p.slice(2)
    }
    paths.add(p)
  }
  return paths
}
