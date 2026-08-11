/**
 * tool-dispatch.test.ts — there is one way to call a tool, and it works.
 *
 * Two independent bugs put ~17 panels out of action, both invisible because
 * the failure is a rejected promise inside a panel nobody has an automated
 * test for:
 *
 *   1. `POST /api/llm-tools/<name>` — a URL that has never existed in this
 *      codebase. `llm_tools` is a Python module namespace, not a route. The
 *      server answers 404. Verified against a live app, not inferred.
 *
 *   2. Raw `fetch` to the real endpoint sends no Authorization header, and
 *      `POST /api/tools/call` is behind `require_auth`. Verified: 401.
 *
 * The one correct path is `api.callTool`, which goes through `request()` —
 * right URL, right body key, Bearer token, timeout, and uniform ApiError
 * handling.
 *
 * This file fails on any NEW use of the dead URL. It records the existing
 * ones rather than pretending they are gone: converting 28 call sites across
 * 18 panels is a careful per-panel job (each has its own abort signal, error
 * shape and response handling), and a regex pass over them produced broken
 * code. The allow-list is a to-do with teeth — it can only shrink.
 */
import { describe, it, expect } from 'vitest'
import { readFileSync, readdirSync, statSync } from 'fs'
import { resolve, dirname, join, relative } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const SRC = resolve(__dirname, '..')

/**
 * Panels still calling the dead URL, pending a per-panel migration to
 * `api.callTool`. Every one of these is a control that does nothing.
 *
 * Do not add to this list. Remove from it.
 */
const KNOWN_BROKEN = new Set([
  'components/electronics/ConstraintManagerPanel.tsx',
  'components/electronics/DrcErcPanel.tsx',
  'components/electronics/EMCPanel.tsx',
  'components/electronics/ICPackagePanel.tsx',
  'components/electronics/MultiBoardPanel.tsx',
  'components/electronics/PCB3DPanel.tsx',
  'components/electronics/PCBInteractiveEditor.tsx',
  'components/electronics/PCBThermalPanel.tsx',
  'components/electronics/SIPanel.tsx',
  'components/electronics/SiliconSynthPanel.tsx',
  'components/electronics/VirtualInstrumentBench.tsx',
  'components/packaging/PackagingMaterialYieldPanel.tsx',
  'components/packaging/PackagingPrePressPanel.tsx',
  'components/plm/ConfiguratorPanel.tsx',
  'components/plm/QuoteToDeliveryPanel.tsx',
  'components/plm/SysMLTracePanel.tsx',
  'routes/GmatViewer.tsx',
  'routes/NodeScript.tsx',
])

function sourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      if (entry === '__tests__' || entry === 'node_modules') continue
      sourceFiles(full, out)
    } else if (/\.tsx?$/.test(entry) && !/\.test\.tsx?$/.test(entry)) {
      out.push(full)
    }
  }
  return out
}

const FILES = sourceFiles(SRC)
// Any fetch whose URL literal contains the dead path, however it is built —
// several sites prefix it with ${API_URL}, which a stricter pattern missed.
const usesDeadUrl = (text: string) => /fetch\(\s*[`'"][^`'"]*?\/api\/llm-tools\//.test(text)

describe('tool dispatch', () => {
  it('no new panel calls the URL that does not exist', () => {
    const offenders = FILES
      .filter((f) => usesDeadUrl(readFileSync(f, 'utf8')))
      .map((f) => relative(SRC, f))
      .filter((f) => !KNOWN_BROKEN.has(f))

    expect(offenders, 'use api.callTool — /api/llm-tools/* answers 404').toEqual([])
  })

  it('the to-do list has no stale entries', () => {
    // A shrinking allow-list is only meaningful if it tracks reality. An entry
    // for a file that no longer uses the dead URL means someone fixed it and
    // the list quietly stopped measuring anything.
    const stillBroken = new Set(
      FILES
        .filter((f) => usesDeadUrl(readFileSync(f, 'utf8')))
        .map((f) => relative(SRC, f)),
    )
    const stale = [...KNOWN_BROKEN].filter((f) => !stillBroken.has(f))

    expect(stale, 'these are fixed — delete them from KNOWN_BROKEN').toEqual([])
  })

  it('api.callTool is the documented path, and it carries auth', () => {
    // /api/tools/call is behind require_auth; a raw fetch sends no token and
    // gets a 401. request() attaches the Bearer token.
    const api = readFileSync(resolve(SRC, 'lib/api.ts'), 'utf8')
    expect(api).toMatch(/callTool:[\s\S]*?request<T>\('\/api\/tools\/call'/)
    expect(api).toMatch(/body: \{ tool: toolName, args \}/)
  })
})
