// Worker that compiles a `.circuit.tsx` source through tscircuit and returns
// the resulting Circuit JSON.
//
// Trade-off (mirrors jscadWorker.js): we keep the eval off the main thread so
// large designs don't freeze the editor. tscircuit's renderer is single-pass
// and synchronous beyond a few async layout phases — the bulk of cost is in
// the schematic-layout + autorouting code, both of which can take hundreds of
// ms even for 20-component designs. Doing this off-thread keeps Monaco
// responsive while a compile is in flight.
//
// Compile pipeline:
//   1. sucrase.transform(source, { transforms: ['typescript', 'jsx'], ... })
//      → CommonJS-shaped JS we can wrap with `new Function(...)`.
//      We rewrite `import` statements to references (R, Capacitor, ...) we
//      pre-bind from `@tscircuit/core`.
//   2. Run the compiled function with the React + tscircuit globals injected.
//      Capture either:
//        - a default export of a JSX element (return Function form), or
//        - a default export that's a function returning JSX, or
//        - a top-level call sequence that constructed a Circuit (legacy).
//   3. new Circuit() ; circuit.add(<element>) ; await circuit.renderUntilSettled()
//      → circuit.getCircuitJson()
//   4. Return the full circuit JSON. Splitting it into schematic / pcb / 3d
//      buckets is done by the main thread (cheap filter on the .type field).
//
// We DO NOT split the circuit JSON server-side because consumers may want
// access to source_* and any/* records that don't cleanly fit one bucket
// (e.g. error objects). Filtering happens at render time.
//
// Cancellation: messages carry a runId. The main thread only forwards the
// latest run's result; older runs return as `stale` so callers no-op.

import { transform as sucraseTransform } from 'sucrase'
import * as React from 'react'
import * as TSC from '@tscircuit/core'
import type { CircuitJson } from '../types/circuit.js'
import type { CircuitCompileRequest, CircuitWorkerResponse } from '../types/workers.js'

// Build a binding map exposed to user code as the module's `exports`.
// We import everything from @tscircuit/core eagerly inside the worker (the
// worker is itself lazily-loaded from the main thread, so first-paint cost
// stays in the main bundle).
const TSC_EXPORTS = TSC

// The set of names users typically import from tscircuit/@tscircuit/core. We
// pre-resolve every named import to its TSC value; unknown names fall back
// to undefined so `new Function` can still bind them.
const KNOWN_IMPORTS: string[] = TSC_EXPORTS && typeof TSC_EXPORTS === 'object'
  ? Object.keys(TSC_EXPORTS)
  : []

// The dynamic `new Function(...)` eval boundary below binds arbitrary
// tscircuit/React exports and the user's own resolved imports by name — none
// of that can be modeled more precisely than `unknown` without hand-rolling a
// parallel type for every possible tscircuit export.
type TscExportsBag = Record<string, unknown>

interface NamespaceImportBinding { kind: 'namespace'; binding: string; source: string }
interface DefaultImportBinding { kind: 'default'; binding: string; source: string }
interface NamedImportBinding { kind: 'named'; orig: string; binding: string; source: string }
type ImportBinding = NamespaceImportBinding | DefaultImportBinding | NamedImportBinding

// Strip & collect import statements. Returns the rewritten JS body plus a
// list of {binding, source, kind} so the caller knows which symbols it must
// bind. We support:
//   - `import X from 'm'`
//   - `import { A, B as C } from 'm'`
//   - `import * as NS from 'm'`
//   - `import 'm'` (side-effect)
// All are stripped — we manually inject the resolved values via the wrapping
// `Function` factory.
const IMPORT_RE = /^[ \t]*import\s+([^;\n]+?)\s+from\s+['"]([^'"\n]+)['"];?[ \t]*$/gm
const SIDE_EFFECT_IMPORT_RE = /^[ \t]*import\s+['"][^'"\n]+['"];?[ \t]*$/gm

function parseImports(src: string): { stripped: string; bindings: ImportBinding[] } {
  const bindings: ImportBinding[] = []
  const stripped = src
    .replace(IMPORT_RE, (_match, clause: string, source: string) => {
      const trimmed = clause.trim()
      // `* as NS`
      const ns = trimmed.match(/^\*\s+as\s+([A-Za-z_$][\w$]*)$/)
      if (ns) {
        bindings.push({ kind: 'namespace', binding: ns[1], source })
        return ''
      }
      // `Default, { A, B }`
      const dual = trimmed.match(/^([A-Za-z_$][\w$]*)\s*,\s*\{([^}]*)\}$/)
      if (dual) {
        bindings.push({ kind: 'default', binding: dual[1], source })
        for (const part of dual[2].split(',')) {
          const p = part.trim()
          if (!p) continue
          const aliased = p.match(/^([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)$/)
          if (aliased) bindings.push({ kind: 'named', orig: aliased[1], binding: aliased[2], source })
          else bindings.push({ kind: 'named', orig: p, binding: p, source })
        }
        return ''
      }
      // `{ A, B }`
      const namedOnly = trimmed.match(/^\{([^}]*)\}$/)
      if (namedOnly) {
        for (const part of namedOnly[1].split(',')) {
          const p = part.trim()
          if (!p) continue
          const aliased = p.match(/^([A-Za-z_$][\w$]*)\s+as\s+([A-Za-z_$][\w$]*)$/)
          if (aliased) bindings.push({ kind: 'named', orig: aliased[1], binding: aliased[2], source })
          else bindings.push({ kind: 'named', orig: p, binding: p, source })
        }
        return ''
      }
      // Plain default import.
      if (/^[A-Za-z_$][\w$]*$/.test(trimmed)) {
        bindings.push({ kind: 'default', binding: trimmed, source })
        return ''
      }
      // Anything we don't recognise: drop the line and warn via console.
      // The compile may still succeed if the user didn't actually need it.
      try {
        console.warn('circuitWorker: unrecognised import clause, dropping:', trimmed)
      } catch { /* ignore */ }
      return ''
    })
    .replace(SIDE_EFFECT_IMPORT_RE, '') // bare side-effect imports are no-ops
  return { stripped, bindings }
}

// Resolve a binding to a runtime value. We treat `tscircuit`, `@tscircuit/core`,
// and `react` as the three known sources; other module specifiers fall through
// to undefined (the user's code will hit a NameError if it tries to use them,
// which surfaces as a clean compile error).
function resolveBinding(b: ImportBinding): unknown {
  const src = b.source
  const isTSC = src === 'tscircuit' || src === '@tscircuit/core'
  const isReact = src === 'react'
  if (b.kind === 'namespace') {
    if (isTSC) return TSC_EXPORTS
    if (isReact) return React
    return {}
  }
  if (b.kind === 'default') {
    if (isReact) return (React as unknown as { default?: unknown }).default ?? React
    if (isTSC) return TSC_EXPORTS // `import t from 'tscircuit'` → namespace-ish
    return undefined
  }
  // named
  const ns: TscExportsBag | null = isReact ? (React as unknown as TscExportsBag) : isTSC ? (TSC_EXPORTS as unknown as TscExportsBag) : null
  if (!ns) return undefined
  return ns[b.orig]
}

// Rewrite a `default export ...` so the wrapping function returns the value.
// We support `export default <expr>` only; named exports of `circuit` / `board`
// are still recognised for parity with tscircuit's CLI, but the v1 flow expects
// a default export.
function rewriteExport(src: string): string {
  // Quick path: explicit default export (most common).
  if (/export\s+default\s+/.test(src)) {
    return src.replace(/export\s+default\s+/, 'return ')
  }
  // Named-export form: `export const circuit = <board>...</board>` or fn.
  const matchConst = src.match(/export\s+(?:const|let|var)\s+(circuit|board|root)\b/)
  if (matchConst) {
    const name = matchConst[1]
    return src
      .replace(/export\s+(const|let|var)\s+/, '$1 ')
      + `\n;return ${name};`
  }
  const matchFn = src.match(/export\s+function\s+(circuit|board|root)\b/)
  if (matchFn) {
    const name = matchFn[1]
    return src.replace(/export\s+function\s+/, 'function ')
      + `\n;return ${name};`
  }
  // Last resort: assume a global `circuit` / `board` was constructed.
  return src + '\n;return (typeof circuit !== "undefined" ? circuit : (typeof board !== "undefined" ? board : null));'
}

type CircuitCompileOutcome = { circuitJson: CircuitJson } | { error: string }

async function compileCircuitInWorker(source: string): Promise<CircuitCompileOutcome> {
  if (!source || !source.trim()) {
    // Empty file → empty circuit JSON. Don't error.
    return { circuitJson: [] }
  }
  // 1. Parse imports, strip them.
  const { stripped, bindings } = parseImports(source)

  // 2. Compile TSX → JS via sucrase. We use `automatic` jsx so the user
  //    doesn't need an explicit `import React`. tscircuit's runtime supplies
  //    the JSX factory via React.createElement / Fragment.
  let compiled: string
  try {
    const out = sucraseTransform(stripped, {
      transforms: ['typescript', 'jsx'],
      jsxRuntime: 'classic',
      jsxPragma: 'React.createElement',
      jsxFragmentPragma: 'React.Fragment',
      production: true,
    })
    compiled = out.code
  } catch (err) {
    return { error: 'Compile error: ' + ((err as Error)?.message || String(err)) }
  }

  // 3. Find the export and rewrite to a `return`.
  const body = rewriteExport(compiled)

  // 4. Build the Function. We bind:
  //    - React (for JSX factory)
  //    - everything from @tscircuit/core (if not already shadowed by user imports)
  //    - the user's resolved imports
  //
  //    Order matters: user imports win over the built-in TSC names, so
  //    `import { Resistor } from 'tscircuit'` shadows our default Resistor
  //    binding cleanly.
  const argNames: string[] = ['React']
  const argValues: unknown[] = [React]
  // First, expose every TSC export as a top-level binding (so user code can
  // reference `<resistor ... />` lowercase tags too — tscircuit registers
  // those via JSX intrinsic lowercase names, no import needed).
  const tscBag = TSC_EXPORTS as unknown as TscExportsBag
  for (const name of KNOWN_IMPORTS) {
    if (argNames.includes(name)) continue
    argNames.push(name)
    argValues.push(tscBag[name])
  }
  // Then user imports — these can override TSC defaults (`import Resistor from
  // './my-r.tsx'` shadows ours). We dedupe by name.
  for (const b of bindings) {
    if (argNames.includes(b.binding)) {
      // overwrite the previous arg value
      const idx = argNames.indexOf(b.binding)
      argValues[idx] = resolveBinding(b)
      continue
    }
    argNames.push(b.binding)
    argValues.push(resolveBinding(b))
  }

  let exported: unknown
  try {
    const factory = new Function(...argNames, body)
    exported = factory(...argValues)
  } catch (err) {
    return { error: 'Eval error: ' + ((err as Error)?.message || String(err)) }
  }

  // 5. The user's default export may be:
  //    - a JSX element (React element)         → wrap into a Circuit and add
  //    - a function returning a JSX element    → call, then wrap
  //    - a Circuit instance (already wrapped)  → use directly
  //    - null/undefined                        → empty circuit
  let element: unknown = exported
  if (typeof element === 'function') {
    try { element = (element as () => unknown)() }
    catch (err) { return { error: 'Default export threw: ' + ((err as Error)?.message || String(err)) } }
  }
  if (element && typeof (element as { then?: unknown }).then === 'function') {
    try { element = await (element as Promise<unknown>) }
    catch (err) { return { error: 'Default export rejected: ' + ((err as Error)?.message || String(err)) } }
  }

  let circuitInstance: { getCircuitJson: () => unknown; renderUntilSettled?: () => Promise<unknown>; render?: () => unknown; add?: (el: unknown) => void }
  if (element && typeof element === 'object' && typeof (element as { getCircuitJson?: unknown }).getCircuitJson === 'function') {
    // Already a Circuit/RootCircuit/IsolatedCircuit-shaped object.
    circuitInstance = element as typeof circuitInstance
  } else if (element == null) {
    // Empty file or null export — return an empty CircuitJSON.
    return { circuitJson: [] }
  } else {
    // Treat as a React element to wrap.
    try {
      const Ctor = TSC_EXPORTS.Circuit || TSC_EXPORTS.RootCircuit
      if (!Ctor) {
        return { error: '@tscircuit/core did not expose a Circuit class' }
      }
      const instance = new Ctor() as unknown as typeof circuitInstance
      instance.add?.(element)
      circuitInstance = instance
    } catch (err) {
      return { error: 'Could not wrap in Circuit: ' + ((err as Error)?.message || String(err)) }
    }
  }

  // 6. Render until settled, then pull the JSON.
  try {
    if (typeof circuitInstance.renderUntilSettled === 'function') {
      await circuitInstance.renderUntilSettled()
    } else if (typeof circuitInstance.render === 'function') {
      circuitInstance.render()
    }
  } catch (err) {
    return { error: 'Render error: ' + ((err as Error)?.message || String(err)) }
  }
  let circuitJson: unknown
  try {
    circuitJson = circuitInstance.getCircuitJson()
  } catch (err) {
    return { error: 'getCircuitJson failed: ' + ((err as Error)?.message || String(err)) }
  }
  // Strip non-cloneable fields defensively. We've seen tscircuit attach
  // function references to a few records; structuredClone refuses those.
  const cleaned = sanitiseForClone(circuitJson)
  return { circuitJson: cleaned as CircuitJson }
}

// Recursively replace function values with `null` so structuredClone can
// transit the result. We don't try to be clever about typed arrays — circuit
// JSON is plain objects + numbers + strings.
function sanitiseForClone(value: unknown, depth = 0): unknown {
  if (depth > 12) return null
  if (value == null) return value
  const t = typeof value
  if (t === 'function') return null
  if (t !== 'object') return value
  if (Array.isArray(value)) {
    return value.map((v) => sanitiseForClone(v, depth + 1))
  }
  const out: Record<string, unknown> = {}
  for (const k of Object.keys(value as Record<string, unknown>)) {
    const v = (value as Record<string, unknown>)[k]
    out[k] = sanitiseForClone(v, depth + 1)
  }
  return out
}

self.addEventListener('message', async (ev: MessageEvent<CircuitCompileRequest>) => {
  const msg = ev.data || ({} as CircuitCompileRequest)
  if (msg.type === 'compile') {
    const { runId, source } = msg
    let res: CircuitCompileOutcome
    try {
      res = await compileCircuitInWorker(source)
    } catch (err) {
      res = { error: (err as Error)?.message || String(err) }
    }
    if ('error' in res) {
      const response: CircuitWorkerResponse = { type: 'error', runId, message: res.error }
      self.postMessage(response)
    } else {
      const response: CircuitWorkerResponse = { type: 'result', runId, circuitJson: res.circuitJson || [] }
      self.postMessage(response)
    }
  }
})
