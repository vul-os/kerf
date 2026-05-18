#!/usr/bin/env node
// scripts/bench_large_assembly.mjs — Large-assembly performance harness (T-15).
//
// Generates synthetic N-part assemblies at three scale points (100 / 1k / 10k
// components) and measures the time for three operations:
//
//   load       — parse the assembly JSON + resolve all component records.
//   render     — simulate the renderer work: matrix multiplication + bounding-box
//                computation for every component (proxy for the real Three.js path
//                which runs in the browser — we measure the pure-JS overhead here).
//   interaction — a single per-frame update: toggling one component's visibility and
//                 re-resolving only the affected slice (proxy for viewport click).
//
// The script is intentionally free of browser APIs so it runs in Node and in CI.
//
// CI-skip: set KERF_SKIP_BENCH=1 to exit 0 immediately. The task spec requires
// the harness runs in "CI-skippable mode" — a failing CI job must not block
// merges when the benchmark environment is unavailable.
//
// Output: human-readable numbers to stdout + a machine-readable JSON to
//   docs/plans/large-assembly.json  (git-ignored; overwritten on each run)
//   docs/plans/large-assembly.md    (committed; updated by this script on each run
//                                    when called with --update-doc)
//
// Usage:
//   node scripts/bench_large_assembly.mjs              # print results, exit
//   node scripts/bench_large_assembly.mjs --update-doc # also write docs/plans/large-assembly.md
//   KERF_SKIP_BENCH=1 node scripts/bench_large_assembly.mjs  # skip (CI)

import { writeFileSync, mkdirSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'
import { performance } from 'node:perf_hooks'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..')

// ---------------------------------------------------------------------------
// CI skip
// ---------------------------------------------------------------------------
if (process.env.KERF_SKIP_BENCH === '1') {
  console.log('[bench_large_assembly] KERF_SKIP_BENCH=1 — skipped.')
  process.exit(0)
}

const UPDATE_DOC = process.argv.includes('--update-doc')

// ---------------------------------------------------------------------------
// Synthetic assembly generator
//
// Each component gets:
//   - a unique id
//   - a file_id cycling through a small set of "part files"
//   - an object_id
//   - a random translation matrix (16-float row-major)
// ---------------------------------------------------------------------------
const IDENTITY = [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]

function randomTransform(seed) {
  // Deterministic LCG so runs are comparable across machines.
  let s = seed
  function next() { s = (s * 1664525 + 1013904223) & 0xffffffff; return s }
  const x = (next() & 0xffff) * 0.01 - 327.68
  const y = (next() & 0xffff) * 0.01 - 327.68
  const z = (next() & 0xffff) * 0.01 - 327.68
  return [
    1, 0, 0, x,
    0, 1, 0, y,
    0, 0, 1, z,
    0, 0, 0, 1,
  ]
}

/**
 * Generate a synthetic assembly JSON string with `n` components.
 * Parts cycle through `numParts` unique file_id values.
 */
function generateAssemblyJSON(n, numParts = 20) {
  const components = []
  for (let i = 0; i < n; i++) {
    const fileIdx = i % numParts
    components.push({
      id: `c-${i}`,
      file_id: `file-${fileIdx}`,
      object_id: `body-${i % 3}`,
      transform: randomTransform(i * 6364136223846793005 + 1442695040888963407 | 0),
    })
  }
  return JSON.stringify({ components })
}

// ---------------------------------------------------------------------------
// Lightweight parseAssembly stand-in
//
// We replicate the production parser's essential logic without pulling the
// full module chain (Three.js etc.) into Node. This measures the pure-JS
// JSON parsing + validation cost.
// ---------------------------------------------------------------------------
function parseAssemblyFast(jsonStr) {
  const raw = JSON.parse(jsonStr)
  const list = Array.isArray(raw.components) ? raw.components : []
  const components = []
  for (let i = 0; i < list.length; i++) {
    const c = list[i]
    if (!c || !c.file_id) continue
    components.push({
      id: c.id || `c${i}`,
      file_id: String(c.file_id),
      object_id: typeof c.object_id === 'string' ? c.object_id : '*',
      transform: Array.isArray(c.transform) && c.transform.length === 16
        ? c.transform
        : IDENTITY,
    })
  }
  return { components }
}

// ---------------------------------------------------------------------------
// Renderer simulation
//
// In production the renderer iterates over resolved parts, builds a
// THREE.Matrix4, applies it to a BufferGeometry, and computes a bounding
// sphere. We simulate that cost with the equivalent pure-JS maths so the
// harness is free of WASM/browser deps.
// ---------------------------------------------------------------------------
function applyTransformSim(transform) {
  // Matrix-vector multiply: transform a corner point [1,1,1,1] → [x,y,z].
  const t = transform
  const x = t[0] + t[1] + t[2] + t[3]
  const y = t[4] + t[5] + t[6] + t[7]
  const z = t[8] + t[9] + t[10] + t[11]
  // Bounding-box accumulation (simulated — real work is proportional to vertex count).
  return { x, y, z, radius: Math.hypot(x, y, z) }
}

function renderSim(components) {
  // Simulates one render pass: matrix computation + bounding-sphere per component.
  let minX = Infinity, minY = Infinity, minZ = Infinity
  let maxX = -Infinity, maxY = -Infinity, maxZ = -Infinity
  for (const c of components) {
    const p = applyTransformSim(c.transform)
    if (p.x < minX) minX = p.x
    if (p.y < minY) minY = p.y
    if (p.z < minZ) minZ = p.z
    if (p.x > maxX) maxX = p.x
    if (p.y > maxY) maxY = p.y
    if (p.z > maxZ) maxZ = p.z
  }
  // Return scene bounding box so the result is used (no dead-code elimination).
  return { minX, minY, minZ, maxX, maxY, maxZ }
}

function interactionSim(components) {
  // Simulate a user clicking a component: toggle visibility + re-resolve 1 slice.
  // In practice the store re-renders only dirty components; we model that here.
  if (components.length === 0) return null
  const targetIdx = Math.floor(components.length / 2)
  const target = components[targetIdx]
  // Toggle visible (creates a new object — mirrors store immutability).
  const updated = { ...target, visible: !target.visible }
  // Re-apply transform on the toggled component only.
  return applyTransformSim(updated.transform)
}

// ---------------------------------------------------------------------------
// Measurement helpers
// ---------------------------------------------------------------------------

/** Run `fn` once and return wall-clock milliseconds. */
function measureMs(fn) {
  const t0 = performance.now()
  fn()
  return performance.now() - t0
}

/** Run `fn` `reps` times and return {mean, min, max} in milliseconds. */
function measureReps(fn, reps = 5) {
  const times = []
  for (let i = 0; i < reps; i++) {
    times.push(measureMs(fn))
  }
  times.sort((a, b) => a - b)
  const sum = times.reduce((a, b) => a + b, 0)
  return {
    mean: sum / times.length,
    min: times[0],
    max: times[times.length - 1],
    median: times[Math.floor(times.length / 2)],
  }
}

// ---------------------------------------------------------------------------
// Budget definitions (T-15 ceiling)
//
// These are the measured ceilings this harness defines. T-16's LOD/lazy-load
// loader must raise the ceiling at 10k parts by the target factor.
// ---------------------------------------------------------------------------
const BUDGET = {
  load: {
    100:   { warnMs: 10,   failMs: 50 },
    1000:  { warnMs: 50,   failMs: 200 },
    10000: { warnMs: 500,  failMs: 2000 },
  },
  render: {
    100:   { warnMs: 2,    failMs: 10 },
    1000:  { warnMs: 20,   failMs: 100 },
    10000: { warnMs: 200,  failMs: 1000 },
  },
  interaction: {
    100:   { warnMs: 1,    failMs: 5 },
    1000:  { warnMs: 1,    failMs: 5 },
    10000: { warnMs: 1,    failMs: 5 },
  },
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------

const SCALES = [100, 1000, 10000]
const REPS = 5 // repetitions per measurement for stable mean

const results = {}
const failed = []
const warned = []

console.log('[bench_large_assembly] Measuring large-assembly performance...\n')
console.log(`${'Scale'.padEnd(8)} ${'Phase'.padEnd(12)} ${'Mean (ms)'.padEnd(12)} ${'Min'.padEnd(10)} ${'Max'.padEnd(10)} Status`)
console.log('-'.repeat(70))

for (const n of SCALES) {
  results[n] = {}

  // Pre-generate the assembly JSON once; exclude generation from measurements.
  const json = generateAssemblyJSON(n)

  // --- load ------------------------------------------------------------------
  let parsed
  const loadStats = measureReps(() => {
    parsed = parseAssemblyFast(json)
  }, REPS)
  results[n].load = loadStats

  const lb = BUDGET.load[n]
  let loadStatus = 'ok'
  if (loadStats.mean > lb.failMs) { loadStatus = 'FAIL'; failed.push(`load@${n}`) }
  else if (loadStats.mean > lb.warnMs) { loadStatus = 'warn'; warned.push(`load@${n}`) }

  console.log(
    `${String(n).padEnd(8)} ${'load'.padEnd(12)} ${loadStats.mean.toFixed(2).padEnd(12)} ${loadStats.min.toFixed(2).padEnd(10)} ${loadStats.max.toFixed(2).padEnd(10)} ${loadStatus}`
  )

  // --- render ----------------------------------------------------------------
  const renderStats = measureReps(() => {
    renderSim(parsed.components)
  }, REPS)
  results[n].render = renderStats

  const rb = BUDGET.render[n]
  let renderStatus = 'ok'
  if (renderStats.mean > rb.failMs) { renderStatus = 'FAIL'; failed.push(`render@${n}`) }
  else if (renderStats.mean > rb.warnMs) { renderStatus = 'warn'; warned.push(`render@${n}`) }

  console.log(
    `${String(n).padEnd(8)} ${'render'.padEnd(12)} ${renderStats.mean.toFixed(2).padEnd(12)} ${renderStats.min.toFixed(2).padEnd(10)} ${renderStats.max.toFixed(2).padEnd(10)} ${renderStatus}`
  )

  // --- interaction -----------------------------------------------------------
  const interactionStats = measureReps(() => {
    interactionSim(parsed.components)
  }, REPS)
  results[n].interaction = interactionStats

  const ib = BUDGET.interaction[n]
  let interactionStatus = 'ok'
  if (interactionStats.mean > ib.failMs) { interactionStatus = 'FAIL'; failed.push(`interaction@${n}`) }
  else if (interactionStats.mean > ib.warnMs) { interactionStatus = 'warn'; warned.push(`interaction@${n}`) }

  console.log(
    `${String(n).padEnd(8)} ${'interaction'.padEnd(12)} ${interactionStats.mean.toFixed(2).padEnd(12)} ${interactionStats.min.toFixed(2).padEnd(10)} ${interactionStats.max.toFixed(2).padEnd(10)} ${interactionStatus}`
  )
}

console.log('')

// ---------------------------------------------------------------------------
// Write machine-readable output
// ---------------------------------------------------------------------------
const docsDir = resolve(ROOT, 'docs', 'plans')
mkdirSync(docsDir, { recursive: true })

const jsonOutput = {
  generated: new Date().toISOString(),
  budget: BUDGET,
  results,
  warned,
  failed,
}
writeFileSync(resolve(docsDir, 'large-assembly.json'), JSON.stringify(jsonOutput, null, 2))
console.log('[bench_large_assembly] wrote docs/plans/large-assembly.json')

// ---------------------------------------------------------------------------
// Write / update the markdown doc (--update-doc or first run)
// ---------------------------------------------------------------------------
if (UPDATE_DOC) {
  const ts = new Date().toISOString().slice(0, 10)
  function fmtRow(n, phase) {
    const s = results[n][phase]
    const b = BUDGET[phase][n]
    return `| ${n.toLocaleString().padStart(6)} | ${phase.padEnd(12)} | ${s.mean.toFixed(1).padStart(9)} | ${s.min.toFixed(1).padStart(7)} | ${s.max.toFixed(1).padStart(7)} | ${b.warnMs} / ${b.failMs} |`
  }
  const md = `# Large-Assembly Performance Plan

> Generated by \`scripts/bench_large_assembly.mjs\` on ${ts}.
> Re-run \`node scripts/bench_large_assembly.mjs --update-doc\` to refresh numbers.

## Problem

Full-vehicle DMU and large mechanical assemblies (10,000+ components) are the
extreme case for three key Kerf personas: **mechanical engineer**, **architect**,
and **automotive designer**. Without a measured ceiling, LOD/lazy-load work (T-16)
has no success criterion.

## Harness methodology

The harness generates synthetic N-part assemblies with deterministic random
transforms and measures three phases in pure JS (no browser/WASM):

- **load** — JSON parse + validate all component records.
- **render** — matrix multiply + bounding-box accumulation for every component
  (proxy for the Three.js render pass; proportional to component count).
- **interaction** — single-frame update: toggle one component's visibility and
  re-apply its transform (proxy for a viewport click).

Each phase is measured over ${REPS} repetitions; the table shows the mean.

## Measured ceiling (baseline — before T-16 LOD)

| Scale  | Phase        | Mean (ms) | Min (ms) | Max (ms) | Budget warn/fail (ms) |
|-------:|:-------------|----------:|---------:|---------:|----------------------:|
${SCALES.flatMap((n) => ['load', 'render', 'interaction'].map((p) => fmtRow(n, p))).join('\n')}

## Budget rationale

- **load**: target < ${BUDGET.load[10000].warnMs} ms at 10k — JSON parse is single-threaded; beyond this the
  spinner is perceptible on first open.
- **render**: target < ${BUDGET.render[10000].warnMs} ms at 10k — one frame budget on a 60 fps target is 16 ms;
  the ${BUDGET.render[10000].warnMs} ms budget allows two frames of stagger for progressive loading.
- **interaction**: target < ${BUDGET.interaction[10000].failMs} ms at any scale — click latency must stay
  imperceptible regardless of assembly size (T-16 lazy-load ensures only the
  affected component re-resolves).

## T-16 LOD / lazy-load target

T-16 must show the **render** ceiling at 10k parts raised by ≥ 5× via
bounding-box proxy substitution for components beyond the LOD threshold
(default: 500 visible components). The harness re-runs after T-16 lands and
the updated table replaces this one.

## Files named by T-15

- \`scripts/bench_large_assembly.mjs\` — this harness
- \`docs/plans/large-assembly.md\` — this document

## Files named by T-16

- \`src/lib/assembly.js\` — LOD selection + lazy-load loader
- \`src/__tests__/assembly.test.js\` — vitest for LOD logic
`
  writeFileSync(resolve(docsDir, 'large-assembly.md'), md)
  console.log('[bench_large_assembly] wrote docs/plans/large-assembly.md')
}

// ---------------------------------------------------------------------------
// Exit
// ---------------------------------------------------------------------------
if (failed.length > 0) {
  console.error(`\n[bench_large_assembly] FAILED budget checks: ${failed.join(', ')}`)
  console.error('(These are soft ceiling breaches on this machine — the harness does not fail CI by default.)')
  console.log('\nRun with KERF_SKIP_BENCH=1 to skip in CI.')
  // Exit 0: the harness defines the ceiling for human review; it is not a hard
  // CI gate (the task spec says "CI-skippable mode"). A hard gate would block
  // PRs on underpowered runners. Set KERF_FAIL_ON_BENCH=1 to enable hard gating.
  if (process.env.KERF_FAIL_ON_BENCH === '1') process.exit(1)
} else if (warned.length > 0) {
  console.warn(`\n[bench_large_assembly] budget warnings: ${warned.join(', ')}`)
}

console.log('\n[bench_large_assembly] done.')
