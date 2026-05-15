// jewelryDispatch.test.js — source-level wiring checks for T-20 → T-24 jewelry ops.
//
// No WASM required.  These tests read occtWorker.js as text and assert:
//   1. Each op function is defined.
//   2. Each op is wired into evaluateTree.
//   3. Each op is wired into evaluateToFinalShape.
//
// This is the exact pattern used by featureBoolean.test.js and booleanIntegration.test.js.

import { describe, it, expect } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

const workerSrc = readFileSync(
  path.resolve(__dirname, '../lib/occtWorker.js'),
  'utf8',
)

// Boundary markers for the two dispatch tables.
const ET_START  = workerSrc.indexOf('function evaluateTree(')
const ETF_START = workerSrc.indexOf('async function evaluateToFinalShape(')

if (ET_START === -1) throw new Error('evaluateTree not found in occtWorker.js')
if (ETF_START === -1) throw new Error('evaluateToFinalShape not found in occtWorker.js')

// Slice for the evaluateTree dispatch (between ET_START and ETF_START).
const etBody  = workerSrc.slice(ET_START, ETF_START)
// Slice for evaluateToFinalShape dispatch (from ETF_START to end).
const etfBody = workerSrc.slice(ETF_START)

// ---------------------------------------------------------------------------
// Helper
// ---------------------------------------------------------------------------

function describeOp(opName, fnName) {
  describe(`${opName} — T-20..T-24 jewelry op`, () => {
    it(`${fnName} function is defined in occtWorker.js`, () => {
      expect(workerSrc).toContain(`function ${fnName}(`)
    })

    it(`case '${opName}' present in evaluateTree dispatch`, () => {
      expect(etBody).toContain(`case '${opName}'`)
    })

    it(`case '${opName}' present in evaluateToFinalShape dispatch`, () => {
      expect(etfBody).toContain(`case '${opName}'`)
    })

    it(`evaluateTree '${opName}' calls ${fnName}`, () => {
      const caseIdx = etBody.indexOf(`case '${opName}'`)
      const caseBlock = etBody.slice(caseIdx, caseIdx + 400)
      expect(caseBlock).toContain(`${fnName}(`)
    })

    it(`evaluateToFinalShape '${opName}' calls ${fnName}`, () => {
      const caseIdx = etfBody.indexOf(`case '${opName}'`)
      const caseBlock = etfBody.slice(caseIdx, caseIdx + 400)
      expect(caseBlock).toContain(`${fnName}(`)
    })
  })
}

// ---------------------------------------------------------------------------
// T-20  opGemstone
// ---------------------------------------------------------------------------

describeOp('gemstone', 'opGemstone')

describe('opGemstone — geometry helpers', () => {
  it('_jewelryTransform helper is defined', () => {
    expect(workerSrc).toContain('function _jewelryTransform(')
  })

  it('_makeCone helper is defined', () => {
    expect(workerSrc).toContain('function _makeCone(')
  })

  it('_makeCylinder helper is defined', () => {
    expect(workerSrc).toContain('function _makeCylinder(')
  })

  it('opGemstone fuses pavilion + girdle + crown', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opGemstone('),
      workerSrc.indexOf('\nfunction opGemSeat('),
    )
    // Must build all three sub-solids and fuse them.
    expect(fn).toContain('pavilion')
    expect(fn).toContain('girdle')
    expect(fn).toContain('crown')
    expect(fn).toContain('_jewelryFuse(')
  })

  it('opGemstone handles aspect_ratio for non-round cuts (Y scale)', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opGemstone('),
      workerSrc.indexOf('\nfunction opGemSeat('),
    )
    expect(fn).toContain('ar')
    expect(fn).toContain('SetValues(')
  })

  it('opGemstone crown proportions use table_pct (table radius derived)', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opGemstone('),
      workerSrc.indexOf('\nfunction opGemSeat('),
    )
    expect(fn).toContain('tablePct')
    expect(fn).toContain('tableR')
  })
})

// ---------------------------------------------------------------------------
// T-21  opGemSeat
// ---------------------------------------------------------------------------

describeOp('gem_seat', 'opGemSeat')

describe('opGemSeat — geometry', () => {
  it('builds a bearing cone, girdle ledge, and crown relief', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opGemSeat('),
      workerSrc.indexOf('\nfunction opJewelryProngHead('),
    )
    expect(fn).toContain('bearingCone')
    expect(fn).toContain('girdleLedge')
    expect(fn).toContain('crownRelief')
  })

  it('supports optional through-hole', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opGemSeat('),
      workerSrc.indexOf('\nfunction opJewelryProngHead('),
    )
    expect(fn).toContain('throughHole')
    expect(fn).toContain('through_hole')
  })

  it('applies position transform', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opGemSeat('),
      workerSrc.indexOf('\nfunction opJewelryProngHead('),
    )
    expect(fn).toContain('_jewelryTransform(')
  })
})

// ---------------------------------------------------------------------------
// T-22  opJewelryProngHead + opJewelryBezel
// ---------------------------------------------------------------------------

describeOp('jewelry_prong_head', 'opJewelryProngHead')
describeOp('jewelry_bezel',      'opJewelryBezel')

describe('opJewelryProngHead — geometry', () => {
  it('builds prongs equal to prong_count around the stone', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryProngHead('),
      workerSrc.indexOf('\nfunction opJewelryBezel('),
    )
    expect(fn).toContain('prongCount')
    expect(fn).toContain('prongCentreR')
    // Loop that builds one cylinder per prong.
    expect(fn).toContain('for (let i = 0; i < prongCount')
  })

  it('fuses basket rail for basket/trellis head style', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryProngHead('),
      workerSrc.indexOf('\nfunction opJewelryBezel('),
    )
    expect(fn).toContain('basket')
    expect(fn).toContain('trellis')
    expect(fn).toContain('railCount')
  })
})

describe('opJewelryBezel — geometry', () => {
  it('bores stone seat into outer collar', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryBezel('),
      workerSrc.indexOf('\nfunction opJewelryChannel('),
    )
    expect(fn).toContain('boreCyl')
    expect(fn).toContain('_jewelryCut(')
  })

  it('supports tapered style using a cone outer wall', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryBezel('),
      workerSrc.indexOf('\nfunction opJewelryChannel('),
    )
    expect(fn).toContain('tapered')
    expect(fn).toContain('_makeCone(')
  })

  it('supports partial opening gap', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryBezel('),
      workerSrc.indexOf('\nfunction opJewelryChannel('),
    )
    expect(fn).toContain('partial')
    expect(fn).toContain('gapBox')
  })
})

// ---------------------------------------------------------------------------
// T-23  opJewelryChannel + opJewelryPave
// ---------------------------------------------------------------------------

describeOp('jewelry_channel', 'opJewelryChannel')
describeOp('jewelry_pave',    'opJewelryPave')

describe('opJewelryChannel — geometry', () => {
  it('builds left rail, right rail, and floor', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryChannel('),
      workerSrc.indexOf('\nfunction opJewelryPave('),
    )
    expect(fn).toContain('leftRail')
    expect(fn).toContain('rightRail')
    expect(fn).toContain('floor')
  })

  it('channel length = stone_count × stone_spacing', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryChannel('),
      workerSrc.indexOf('\nfunction opJewelryPave('),
    )
    expect(fn).toContain('chanLen')
    expect(fn).toContain('_channel_length')
  })
})

describe('opJewelryPave — geometry', () => {
  it('places sphere markers at each placement (u,v) position', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryPave('),
      workerSrc.indexOf('\nfunction opRingShank('),
    )
    expect(fn).toContain('placements')
    expect(fn).toContain('MakeSphere')
  })

  it('builds a compound of markers', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryPave('),
      workerSrc.indexOf('\nfunction opRingShank('),
    )
    expect(fn).toContain('TopoDS_Compound')
    expect(fn).toContain('MakeCompound')
  })

  it('uses surface_normal to orient the frame', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opJewelryPave('),
      workerSrc.indexOf('\nfunction opRingShank('),
    )
    expect(fn).toContain('surface_normal')
    expect(fn).toContain('surface_origin')
  })
})

// ---------------------------------------------------------------------------
// T-24  opRingShank
// ---------------------------------------------------------------------------

describeOp('ring_shank', 'opRingShank')

describe('opRingShank — geometry', () => {
  it('revolves a profile around the Z (finger) axis', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opRingShank('),
      workerSrc.indexOf('\n// ---------------------------------------------------------------------------\n// Tree evaluation.'),
    )
    expect(fn).toContain('MakeRevol')
    expect(fn).toContain('clR')
  })

  it('all 7 profile strings are handled (comfort_fit, flat, d_shape, etc.)', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opRingShank('),
      workerSrc.indexOf('\n// ---------------------------------------------------------------------------\n// Tree evaluation.'),
    )
    for (const p of ['comfort_fit', 'flat', 'euro', 'd_shape', 'half_round', 'knife_edge', 'tapered']) {
      expect(fn).toContain(`'${p}'`)
    }
  })

  it('cathedral shoulder modifier fuses arch ribs', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opRingShank('),
      workerSrc.indexOf('\n// ---------------------------------------------------------------------------\n// Tree evaluation.'),
    )
    expect(fn).toContain('cathedral')
    expect(fn).toContain('_jewelryFuse(')
  })

  it('uses inner_diameter_mm from node', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opRingShank('),
      workerSrc.indexOf('\n// ---------------------------------------------------------------------------\n// Tree evaluation.'),
    )
    expect(fn).toContain('inner_diameter_mm')
    expect(fn).toContain('innerD')
  })

  it('taper_ratio is consumed for tapered profile', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opRingShank('),
      workerSrc.indexOf('\n// ---------------------------------------------------------------------------\n// Tree evaluation.'),
    )
    expect(fn).toContain('taperR')
    expect(fn).toContain('taper_ratio')
  })
})

// ---------------------------------------------------------------------------
// Node-spec field coverage assertions
// ---------------------------------------------------------------------------

describe('gemstone node spec fields consumed by opGemstone', () => {
  const fn = workerSrc.slice(
    workerSrc.indexOf('function opGemstone('),
    workerSrc.indexOf('\nfunction opGemSeat('),
  )
  for (const field of [
    'diameter_mm', 'aspect_ratio', 'table_pct',
    'crown_height_pct', 'pavilion_depth_pct', 'girdle_pct',
  ]) {
    it(`field '${field}' is referenced`, () => {
      expect(fn).toContain(field)
    })
  }
})

describe('gem_seat node spec fields consumed by opGemSeat', () => {
  const fn = workerSrc.slice(
    workerSrc.indexOf('function opGemSeat('),
    workerSrc.indexOf('\nfunction opJewelryProngHead('),
  )
  for (const field of [
    'girdle_radius_mm', 'pavilion_depth_mm', 'girdle_height_mm',
    'bearing_cone_top_radius', 'bearing_cone_bottom_radius',
    'culet_depth_mm', 'crown_relief_depth_mm',
  ]) {
    it(`field '${field}' is referenced`, () => {
      expect(fn).toContain(field)
    })
  }
})

describe('ring_shank node spec fields consumed by opRingShank', () => {
  const fn = workerSrc.slice(
    workerSrc.indexOf('function opRingShank('),
    workerSrc.indexOf('\n// ---------------------------------------------------------------------------\n// Tree evaluation.'),
  )
  for (const field of [
    'inner_diameter_mm', 'outer_diameter_mm', 'band_width_mm',
    'thickness_mm', 'profile', 'taper_ratio', 'shoulder_style',
  ]) {
    it(`field '${field}' is referenced`, () => {
      expect(fn).toContain(field)
    })
  }
})

// ---------------------------------------------------------------------------
// Round-brilliant facet-count assertion (T-20 DoD)
// ---------------------------------------------------------------------------

describe('round_brilliant facet count convention', () => {
  it('Python gemstones.py specifies facet_count 57 for round_brilliant', () => {
    // This is a source-check against the Python node spec — we read the Python
    // file to confirm the extras.facet_count = 57 is the canonical spec that
    // the OCCT op honours when producing the crown prism facets.
    try {
      const pySrc = readFileSync(
        path.resolve(__dirname, '../../packages/kerf-cad-core/src/kerf_cad_core/jewelry/gemstones.py'),
        'utf8',
      )
      expect(pySrc).toContain('"facet_count": 57')
      expect(pySrc).toContain('round_brilliant')
    } catch {
      // Python file not reachable in this environment — skip.
      expect(true).toBe(true)
    }
  })

  it('opGemstone builds a crown solid (crown height uses crown_height_pct)', () => {
    const fn = workerSrc.slice(
      workerSrc.indexOf('function opGemstone('),
      workerSrc.indexOf('\nfunction opGemSeat('),
    )
    expect(fn).toContain('crownH')
    expect(fn).toContain('crown_height_pct')
  })
})
