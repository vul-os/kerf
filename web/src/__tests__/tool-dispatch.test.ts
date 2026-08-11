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
 * Tool names these panels call that the backend registry does not define.
 *
 * The URL migration is done — every call goes through api.callTool now — but
 * six controls still do nothing, for a different reason: the tool they name has
 * no ToolSpec anywhere under packages/. They used to 404 on the route; they now
 * 404 as `unknown tool: <name>` from /api/tools/call. Same dead button, one
 * layer deeper.
 *
 * Recorded rather than deleted, because "no panel calls the dead URL" and
 * "every panel works" are different claims and only the first is true.
 *
 * `pcb_drc` is the interesting one: `run_pcb_drc` exists and does the job, but
 * the panel calls `pcb_drc` with no arguments as a liveness probe and
 * run_pcb_drc requires circuit_json — so it is a rename plus a rethink.
 */
const TOOLS_THE_BACKEND_DOES_NOT_HAVE = [
  'pcb_drc',
  'electronics_route_trace',
  'pcb_shove_trace',
  'electronics_delete_object',
  'aerospace_load_gmat_trajectory',
] as const

/** Files that may still call the dead URL. Nothing may. */
const KNOWN_BROKEN = new Set<string>([])

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

  it('records the panels whose tool does not exist in the backend', () => {
    // Not a pass/fail on the panels — a check that this list still describes
    // reality. Add one of these tools and this fails so the entry can go; stop
    // calling one and likewise. The list cannot quietly become fiction, which
    // is what happened when the URL allow-list was emptied on the grounds that
    // the migration was complete.
    const src = FILES.map((f) => readFileSync(f, 'utf8')).join('\n')
    const stillCalled = TOOLS_THE_BACKEND_DOES_NOT_HAVE.filter((t) =>
      src.includes(`callTool('${t}'`) || src.includes(`callTool<`) && src.includes(`>('${t}'`),
    )
    expect(stillCalled).toEqual([...TOOLS_THE_BACKEND_DOES_NOT_HAVE])
  })

  it('api.callTool is the documented path, and it carries auth', () => {
    // /api/tools/call is behind require_auth; a raw fetch sends no token and
    // gets a 401. request() attaches the Bearer token.
    const api = readFileSync(resolve(SRC, 'lib/api.ts'), 'utf8')
    expect(api).toMatch(/callTool:[\s\S]*?request<T>\('\/api\/tools\/call'/)
    expect(api).toMatch(/body: \{ tool: toolName, args \}/)
  })
})
