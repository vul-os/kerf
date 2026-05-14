// featureCutFromSketch.test.js — pure-JS coverage for the cut_from_sketch
// feature op.
//
// The OCCT worker function opCutFromSketch itself requires the ~5 MB WASM
// blob and is exercised only in integration tests.  This suite covers:
//
//   1. Node shape — verify that a cut_from_sketch node produced by
//      parseFeature survives a round-trip with the right fields.
//   2. newFeatureId prefix — verifies the id generator uses the right prefix.
//   3. Worker dispatch surface — verifies that the switch table in
//      occtWorker.js contains a 'cut_from_sketch' case by inspecting the
//      source text (fast proxy for "the handler is wired", matches the
//      anti-pattern documented in the planning doc for dormant ops).

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

import { parseFeature, serializeFeature, newFeatureId } from '../lib/occtRunner.js'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// ── 1. Node round-trip ────────────────────────────────────────────────────────

describe('cut_from_sketch node round-trip', () => {
  const sampleNode = {
    id: 'cut-1',
    op: 'cut_from_sketch',
    target_id: 'pad-1',
    target_face_id: 7,
    sketch_path: '/slot.sketch',
    depth: 4.0,
    reverse: false,
  }

  it('parseFeature preserves a cut_from_sketch node unchanged', () => {
    const json = JSON.stringify({
      version: 1,
      name: 'Bracket',
      features: [
        { id: 'pad-1', op: 'pad', sketch_path: '/base.sketch', height: 20 },
        sampleNode,
      ],
    })
    const parsed = parseFeature(json)
    expect(parsed.features).toHaveLength(2)
    const node = parsed.features[1]
    expect(node.op).toBe('cut_from_sketch')
    expect(node.target_id).toBe('pad-1')
    expect(node.target_face_id).toBe(7)
    expect(node.sketch_path).toBe('/slot.sketch')
    expect(node.depth).toBe(4.0)
    expect(node.reverse).toBe(false)
  })

  it('serializeFeature round-trips a cut_from_sketch node', () => {
    const tree = {
      version: 1,
      name: 'Bracket',
      features: [sampleNode],
      default_config: '',
      configurations: [],
    }
    const serialised = serializeFeature(tree)
    const back = JSON.parse(serialised)
    expect(back.features[0]).toMatchObject(sampleNode)
  })

  it('reverse:true round-trips correctly', () => {
    const node = { ...sampleNode, id: 'cut-2', reverse: true }
    const json = JSON.stringify({ version: 1, name: 'T', features: [node] })
    const parsed = parseFeature(json)
    expect(parsed.features[0].reverse).toBe(true)
  })
})

// ── 2. newFeatureId prefix ────────────────────────────────────────────────────

describe('newFeatureId for cut_from_sketch nodes', () => {
  it('generates an id with the cut prefix', () => {
    // The Python backend uses next_node_id(content, 'cut') — the resulting
    // id is 'cut-N'.  The JS helper mirrors the same prefix convention.
    const id = newFeatureId('cut')
    expect(id).toMatch(/^cut-/)
  })
})

// ── 3. Worker switch-table wiring ─────────────────────────────────────────────

describe('occtWorker.js switch table', () => {
  it("contains a 'cut_from_sketch' case so the op is not dormant", () => {
    const workerSrc = readFileSync(
      path.resolve(__dirname, '../lib/occtWorker.js'),
      'utf8',
    )
    // Expect the literal case label to appear at least twice — once in
    // evaluateTree and once in evaluateToFinalShape.
    const matches = workerSrc.match(/case 'cut_from_sketch'/g)
    expect(matches).not.toBeNull()
    expect(matches.length).toBeGreaterThanOrEqual(2)
  })

  it("contains the opCutFromSketch function definition", () => {
    const workerSrc = readFileSync(
      path.resolve(__dirname, '../lib/occtWorker.js'),
      'utf8',
    )
    expect(workerSrc).toContain('function opCutFromSketch(')
  })
})
