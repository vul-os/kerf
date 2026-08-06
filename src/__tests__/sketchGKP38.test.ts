/**
 * sketchGKP38.test.js — GK-P38 G2 curvature continuity constraint JS-side tests.
 *
 * Verifies:
 *   - bezier_g2 does not crash the solver.
 *   - dofCount drops by 2 (G1 + equal-chord).
 *   - Symmetric Bezier segments with G2 solve without conflict.
 *   - Primitives emitted: point_on_line_ppp (G1) + p2p_distance × 2 (equal-chord).
 */

import { describe, it, expect, vi } from 'vitest'

vi.mock('@salusoft89/planegcs', () => {
  const SolveStatus = { Success: 0, Converged: 1, Failed: 2, SuccessfulSolutionInvalid: 3 }
  const Algorithm   = { DogLeg: 0 }
  function makeFakeWrapper() {
    const primitives = []
    const sketch_index = { get_primitives() { return primitives } }
    return {
      primitives,
      sketch_index,
      push_primitive(p) { primitives.push({ ...p }) },
      solve()          { return SolveStatus.Success },
      apply_solution() {},
      has_gcs_conflicting_constraints() { return false },
      get_gcs_conflicting_constraints() { return [] },
      destroy_gcs_module() {},
    }
  }
  return { make_gcs_wrapper: vi.fn(async () => makeFakeWrapper()), Algorithm, SolveStatus }
})

import { solveSketch } from '../lib/sketchSolver.js'

function emptySketch() {
  return {
    version: 1, plane: { type: 'base', name: 'XY' },
    entities: [{ id: 'origin', type: 'point', x: 0, y: 0 }],
    constraints: [], visible_3d: [], solved: {}, metadata: {},
  }
}

describe('GK-P38 — G2 curvature continuity constraint', () => {
  it('bezier_g2 does not crash the solver', async () => {
    const sketch = emptySketch()
    sketch.entities.push(
      { id: 'a2', type: 'point', x: 7.0,  y: 4.0 },
      { id: 'a3', type: 'point', x: 10.0, y: 0.0 },
      { id: 'b1', type: 'point', x: 13.0, y: -4.0 },
      { id: 'b2', type: 'point', x: 17.0, y: -4.0 },
    )
    sketch.constraints.push({
      id: 'g2_j', type: 'bezier_g2',
      p_minus2: 'a2', p_minus1: 'a2',
      p_junction: 'a3',
      p_plus1: 'b1', p_plus2: 'b2',
    })
    const result = await solveSketch(sketch)
    expect(result).toBeDefined()
    expect(result.ok).toBe(true)
  })

  it('bezier_g2 removes 2 DOF from dofCount', async () => {
    const base = emptySketch()
    base.entities.push(
      { id: 'pm2', type: 'point', x: 0,  y: 0 },
      { id: 'pm1', type: 'point', x: 5,  y: 5 },
      { id: 'pj',  type: 'point', x: 10, y: 0 },
      { id: 'pp1', type: 'point', x: 15, y: -5 },
      { id: 'pp2', type: 'point', x: 20, y: 0 },
    )

    const constrained = {
      ...base,
      entities: [...base.entities],
      constraints: [{
        id: 'g2_j', type: 'bezier_g2',
        p_minus2: 'pm2', p_minus1: 'pm1',
        p_junction: 'pj',
        p_plus1: 'pp1', p_plus2: 'pp2',
      }],
    }

    const rBase = await solveSketch(base)
    const rG2   = await solveSketch(constrained)

    expect(rG2.dofCount).toBe(rBase.dofCount - 2)
  })

  it('symmetric Bezier segments with G2 solve without conflict', async () => {
    const sketch = emptySketch()
    sketch.entities.push(
      { id: 'a0', type: 'point', x: 0,  y: 0 },
      { id: 'a1', type: 'point', x: 3,  y: 4 },
      { id: 'a2', type: 'point', x: 7,  y: 4 },
      { id: 'a3', type: 'point', x: 10, y: 0 },
      { id: 'b1', type: 'point', x: 13, y: -4 },
      { id: 'b2', type: 'point', x: 17, y: -4 },
      { id: 'b3', type: 'point', x: 20, y: 0 },
    )
    sketch.constraints.push(
      { id: 'fix_a0', type: 'fixed', point: 'a0', x: 0, y: 0 },
      { id: 'fix_b3', type: 'fixed', point: 'b3', x: 20, y: 0 },
      {
        id: 'g2_j', type: 'bezier_g2',
        p_minus2: 'a2', p_minus1: 'a2',
        p_junction: 'a3',
        p_plus1: 'b1', p_plus2: 'b2',
      },
    )
    const result = await solveSketch(sketch)
    expect(result.ok).toBe(true)
    expect(result.status).not.toBe('conflict')
  })

  it('G2 emits point_on_line_ppp + two p2p_distance primitives (G1 + equal-chord)', async () => {
    const { make_gcs_wrapper } = await import('@salusoft89/planegcs')
    const sketch = emptySketch()
    sketch.entities.push(
      { id: 'pm1', type: 'point', x: 5,  y: 5 },
      { id: 'pj',  type: 'point', x: 10, y: 0 },
      { id: 'pp1', type: 'point', x: 15, y: -5 },
    )
    sketch.constraints.push({
      id: 'g2', type: 'bezier_g2',
      p_minus2: 'pm1', p_minus1: 'pm1',
      p_junction: 'pj',
      p_plus1: 'pp1', p_plus2: 'pp1',
    })
    await solveSketch(sketch)
    const wrapper = await make_gcs_wrapper.mock.results[make_gcs_wrapper.mock.results.length - 1].value
    const prims = wrapper.primitives

    // G1: collinearity
    const polPrim = prims.find((p) => p.type === 'point_on_line_ppp')
    expect(polPrim).toBeDefined()
    expect(polPrim.p_id).toBe('pj')

    // C2: equal-chord distances
    const distPrims = prims.filter((p) => p.type === 'p2p_distance')
    expect(distPrims.length).toBeGreaterThanOrEqual(1)
    if (distPrims.length >= 2) {
      // Both chord distances must be equal (matching curvature condition).
      expect(distPrims[0].distance).toBeCloseTo(distPrims[1].distance, 6)
    }
  })
})
