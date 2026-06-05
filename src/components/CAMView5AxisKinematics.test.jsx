// CAMView5AxisKinematics.test.jsx — Vitest structural tests for the
// machine-kinematics + multi-controller post UI additions.
//
// Tests:
//  1. fiveAxisBackendArgs passes machineKinematic into the backend args.
//  2. All three kinematic values are accepted (head_table, table_table, head_head).
//  3. fiveAxisBackendArgs kinematic_family defaults to 'head_table' when omitted.
//  4. Source structure: data-testid="machine-kinematic-select" present.
//  5. Source structure: Heidenhain + Siemens post options present.
//  6. kinematic_family flows through to both 3plus2 and 5axis_finish.

import { describe, it, expect, beforeAll, vi } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

vi.mock('../store/auth.js', () => ({ useAuth: { getState: () => ({ accessToken: null }) } }))
vi.mock('./ToolDBPanel.jsx', () => ({
  default: () => null,
  ToolPicker: () => null,
}))

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const camViewSrc = readFileSync(path.resolve(__dirname, 'CAMView.jsx'), 'utf8')

// ── 1–3. fiveAxisBackendArgs with machineKinematic ────────────────────────────

describe('fiveAxisBackendArgs with machineKinematic', () => {
  let fiveAxisBackendArgs

  beforeAll(async () => {
    const mod = await import('./CAMView.jsx')
    fiveAxisBackendArgs = mod.fiveAxisBackendArgs
  })

  it('kinematic_family defaults to head_table when undefined', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'B', '15', '0', '', false, undefined)
    expect(args.kinematic_family).toBe('head_table')
  })

  it('kinematic_family defaults to head_table when null', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'B', '15', '0', '', false, null)
    expect(args.kinematic_family).toBe('head_table')
  })

  it('kinematic_family = table_table is passed through (5axis_finish)', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'B', '20', '0', '', false, 'table_table')
    expect(args.kinematic_family).toBe('table_table')
    expect(args.operation).toBe('5axis_finish')
  })

  it('kinematic_family = head_head is passed through (5axis_finish)', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'B', '20', '0', '', false, 'head_head')
    expect(args.kinematic_family).toBe('head_head')
  })

  it('kinematic_family = head_table is passed through (3plus2)', () => {
    const args = fiveAxisBackendArgs('5axis_indexed', 'indexed_rough', 'B', '0', '0', '', false, 'head_table')
    expect(args.operation).toBe('3plus2')
    expect(args.kinematic_family).toBe('head_table')
  })

  it('kinematic_family = table_table is passed through (3plus2)', () => {
    const args = fiveAxisBackendArgs('5axis_indexed', 'indexed_rough', 'B', '0', '0', '', false, 'table_table')
    expect(args.operation).toBe('3plus2')
    expect(args.kinematic_family).toBe('table_table')
  })

  it('swarf strategy still gets kinematic_family', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'swarf', 'B', '20', '0', '', false, 'head_head')
    expect(args.tilt_deg).toBe(0)
    expect(args.kinematic_family).toBe('head_head')
  })

  it('useTcp=true is still passed through with kinematic', () => {
    const args = fiveAxisBackendArgs('5axis_cont', 'contour_tilted', 'B', '15', '0', '', true, 'head_table')
    expect(args.use_tcp).toBe(true)
    expect(args.kinematic_family).toBe('head_table')
  })
})

// ── 4–6. Source structure ─────────────────────────────────────────────────────

describe('CAMView source structure — machine kinematics + multi-post', () => {
  it('contains data-testid="machine-kinematic-select"', () => {
    expect(camViewSrc).toMatch(/data-testid="machine-kinematic-select"/)
  })

  it('head-table option present in machine kinematic select', () => {
    expect(camViewSrc).toMatch(/head_table/)
  })

  it('table-table option present in machine kinematic select', () => {
    expect(camViewSrc).toMatch(/table_table/)
  })

  it('head-head option present in machine kinematic select', () => {
    expect(camViewSrc).toMatch(/head_head/)
  })

  it('heidenhain post option present in post5x-select', () => {
    expect(camViewSrc).toMatch(/heidenhain/)
  })

  it('siemens post option present in post5x-select', () => {
    expect(camViewSrc).toMatch(/siemens/)
  })

  it('TRAORI label present in siemens option', () => {
    expect(camViewSrc).toMatch(/TRAORI/)
  })

  it('M128 label present in heidenhain option', () => {
    expect(camViewSrc).toMatch(/M128/)
  })

  it('G43.4 label present in fanuc option', () => {
    expect(camViewSrc).toMatch(/G43\.4/)
  })

  it('machineKinematic state variable declared', () => {
    expect(camViewSrc).toMatch(/machineKinematic/)
  })

  it('setMachineKinematic state setter declared', () => {
    expect(camViewSrc).toMatch(/setMachineKinematic/)
  })

  it('fiveAxisBackendArgs receives machineKinematic argument', () => {
    expect(camViewSrc).toMatch(/fiveAxisBackendArgs.*machineKinematic/)
  })
})
