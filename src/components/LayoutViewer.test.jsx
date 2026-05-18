// LayoutViewer.test.jsx — Vitest assertions for LayoutViewer data-layer helpers.
//
// Pure data-layer / pure-logic tests only (no React DOM rendering / JSDOM
// canvas). The rendering and interaction logic lives in layoutCanvas.js and
// layoutPalette.js; those are covered by their own test files. Here we test
// the helpers that LayoutViewer itself exports / relies on:
//
//  - resolveTopShapes (internal logic exported for testing via re-export in
//    this file's sibling helpers — we test the same logic by importing
//    layoutCanvas helpers directly)
//  - Layer-collection from a parsed layout tree
//  - The view reducer transitions (pan, zoom-to, set)
//  - Integration: fitBounds + worldToScreen centroid oracle

import { describe, it, expect } from 'vitest'
import {
  worldToScreen,
  screenToWorld,
  fitBounds,
  hitTest,
  shapeBounds,
} from '../lib/layoutCanvas.js'
import {
  sky130Palette,
  getPaletteColor,
  defaultLayerColor,
} from '../lib/layoutPalette.js'

// ── Utilities mirrored from LayoutViewer ─────────────────────────────────────

function collectLayers(shapes) {
  const ids = new Set()
  function visit(s) {
    if (!s) return
    if (s.layer != null) ids.add(s.layer)
    if (s.kind === 'ref' && Array.isArray(s.shapes)) s.shapes.forEach(visit)
  }
  shapes.forEach(visit)
  return [...ids].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0))
}

function resolveTopShapes(layout) {
  if (!layout) return []
  const topName = layout.topCell
  const cells   = layout.cells ?? []
  const top     = topName ? cells.find(c => c.name === topName) : cells[0]
  return top ? (top.shapes ?? []) : []
}

// Simple view reducer (mirrors the one in the component)
function viewReducer(state, action) {
  switch (action.type) {
    case 'SET': return action.view
    case 'PAN': return { ...state, offsetX: state.offsetX + action.dx, offsetY: state.offsetY + action.dy }
    case 'ZOOM_TO': {
      const { factor, px, py } = action
      const newZoom = state.zoom * factor
      const scale   = newZoom / state.zoom
      return {
        zoom:    newZoom,
        offsetX: px - scale * (px - state.offsetX),
        offsetY: py - scale * (py - state.offsetY),
      }
    }
    default: return state
  }
}

// ── resolveTopShapes ──────────────────────────────────────────────────────────

describe('resolveTopShapes', () => {
  it('returns empty array when layout is null', () => {
    expect(resolveTopShapes(null)).toEqual([])
  })

  it('returns shapes of the named topCell', () => {
    const layout = {
      topCell: 'top',
      cells: [
        { name: 'other', shapes: [{ kind: 'box', layer: 1, x: 0, y: 0, w: 5, h: 5 }] },
        { name: 'top',   shapes: [{ kind: 'box', layer: 68, x: 0, y: 0, w: 10, h: 10 }] },
      ],
    }
    const shapes = resolveTopShapes(layout)
    expect(shapes).toHaveLength(1)
    expect(shapes[0].layer).toBe(68)
  })

  it('falls back to first cell when topCell is not specified', () => {
    const layout = {
      cells: [
        { name: 'first', shapes: [{ kind: 'polygon', layer: 66, points: [] }] },
        { name: 'second', shapes: [] },
      ],
    }
    const shapes = resolveTopShapes(layout)
    expect(shapes).toHaveLength(1)
    expect(shapes[0].layer).toBe(66)
  })

  it('returns empty when topCell name not found', () => {
    const layout = { topCell: 'missing', cells: [{ name: 'real', shapes: [{}] }] }
    expect(resolveTopShapes(layout)).toEqual([])
  })
})

// ── collectLayers ─────────────────────────────────────────────────────────────

describe('collectLayers', () => {
  it('returns empty array when there are no shapes', () => {
    expect(collectLayers([])).toEqual([])
  })

  it('collects unique layer ids', () => {
    const shapes = [
      { kind: 'box',     layer: 68, x: 0, y: 0, w: 1, h: 1 },
      { kind: 'polygon', layer: 66, points: [] },
      { kind: 'box',     layer: 68, x: 1, y: 0, w: 1, h: 1 }, // duplicate
    ]
    const layers = collectLayers(shapes)
    expect(layers).toHaveLength(2)
    expect(layers).toContain(66)
    expect(layers).toContain(68)
  })

  it('recurses into ref shapes', () => {
    const shapes = [
      {
        kind: 'ref',
        shapes: [
          { kind: 'box', layer: 71, x: 0, y: 0, w: 1, h: 1 },
        ],
      },
    ]
    expect(collectLayers(shapes)).toContain(71)
  })

  it('ignores shapes without a layer', () => {
    const shapes = [{ kind: 'text', x: 0, y: 0, label: 'hi' }]
    expect(collectLayers(shapes)).toHaveLength(0)
  })
})

// ── View reducer ──────────────────────────────────────────────────────────────

describe('viewReducer', () => {
  const init = { offsetX: 0, offsetY: 0, zoom: 1 }

  it('SET replaces the view', () => {
    const v = viewReducer(init, { type: 'SET', view: { offsetX: 10, offsetY: 20, zoom: 3 } })
    expect(v.offsetX).toBe(10)
    expect(v.offsetY).toBe(20)
    expect(v.zoom).toBe(3)
  })

  it('PAN shifts offsets', () => {
    const v = viewReducer(init, { type: 'PAN', dx: 5, dy: -3 })
    expect(v.offsetX).toBe(5)
    expect(v.offsetY).toBe(-3)
    expect(v.zoom).toBe(1)
  })

  it('ZOOM_TO keeps the zoom point fixed in world space', () => {
    const start = { offsetX: 0, offsetY: 0, zoom: 1 }
    const px = 100, py = 100
    const factor = 2
    const v = viewReducer(start, { type: 'ZOOM_TO', factor, px, py })

    // After zooming, world point at (px,py) should remain at screen (px,py)
    const worldBefore = screenToWorld({ x: px, y: py }, start)
    const worldAfter  = screenToWorld({ x: px, y: py }, v)

    expect(Math.abs(worldBefore.x - worldAfter.x)).toBeLessThan(1e-9)
    expect(Math.abs(worldBefore.y - worldAfter.y)).toBeLessThan(1e-9)
  })

  it('ZOOM_TO doubles the zoom', () => {
    const v = viewReducer(init, { type: 'ZOOM_TO', factor: 2, px: 0, py: 0 })
    expect(v.zoom).toBe(2)
  })
})

// ── fitBounds + centroid oracle ───────────────────────────────────────────────

describe('fitBounds integration — centroid at viewport centre', () => {
  const viewport = { width: 800, height: 600 }

  it('inverter-style multi-layer layout: centroid at screen centre', () => {
    // Simulate a small inverter layout with shapes on several SKY130 layers
    const shapes = [
      { kind: 'box', layer: 64, x:   0, y:   0, w: 200, h: 100 }, // nwell
      { kind: 'box', layer: 65, x:  20, y:  10, w:  40, h:  80 }, // diff
      { kind: 'box', layer: 66, x:  80, y:   0, w:  20, h: 100 }, // poly
      { kind: 'box', layer: 68, x:   0, y: -10, w: 200, h:  20 }, // met1
    ]
    const view = fitBounds(shapes, viewport)

    // Bounding box: x [0,200], y [-10,100] → centroid (100, 45)
    const cx = 100, cy = 45
    const s = worldToScreen({ x: cx, y: cy }, view)

    expect(Math.abs(s.x - viewport.width  / 2)).toBeLessThan(1)
    expect(Math.abs(s.y - viewport.height / 2)).toBeLessThan(1)
  })

  it('zoom from fitBounds lets at least the full layout fit on screen', () => {
    const shapes = [{ kind: 'box', layer: 68, x: 0, y: 0, w: 500, h: 300 }]
    const view = fitBounds(shapes, viewport)

    const corners = [
      { x: 0,   y: 0   },
      { x: 500, y: 0   },
      { x: 500, y: 300 },
      { x: 0,   y: 300 },
    ]
    for (const c of corners) {
      const s = worldToScreen(c, view)
      expect(s.x).toBeGreaterThanOrEqual(0)
      expect(s.x).toBeLessThanOrEqual(viewport.width)
      expect(s.y).toBeGreaterThanOrEqual(0)
      expect(s.y).toBeLessThanOrEqual(viewport.height)
    }
  })
})

// ── Layer colour integration ──────────────────────────────────────────────────

describe('layer colour integration with SKY130 palette', () => {
  it('met1 (layerNum=68, datatype=20) resolves to a non-null colour', () => {
    const c = getPaletteColor(sky130Palette, { layerNum: 68, datatype: 20 })
    expect(c).not.toBeNull()
    expect(typeof c.fill).toBe('string')
  })

  it('unknown layer resolves to defaultLayerColor', () => {
    const c = getPaletteColor(sky130Palette, { layerNum: 9999, datatype: 9999 }) ?? defaultLayerColor
    expect(c).toBe(defaultLayerColor)
  })

  it('layerColors map built from collectLayers has entry for every layer', () => {
    const shapes = [
      { kind: 'box', layer: 68, x: 0, y: 0, w: 1, h: 1 },
      { kind: 'box', layer: 66, x: 0, y: 0, w: 1, h: 1 },
    ]
    const layers = collectLayers(shapes)
    const m = new Map()
    for (const lid of layers) {
      const c = getPaletteColor(
        sky130Palette,
        typeof lid === 'number' ? { layerNum: lid, datatype: 0 } : lid,
      ) ?? defaultLayerColor
      m.set(lid, c)
    }
    expect(m.size).toBe(2)
    for (const lid of layers) {
      expect(m.has(lid)).toBe(true)
      expect(typeof m.get(lid).fill).toBe('string')
    }
  })
})

// ── hitTest contract (Box) — required by T-238 spec ──────────────────────────

describe('hitTest contract — Box (spec oracle)', () => {
  const box = { kind: 'box', x: 0, y: 0, w: 100, h: 100 }

  it('accepts a point inside', () => {
    expect(hitTest(box, { x: 50, y: 50 })).toBe(true)
  })

  it('rejects a point outside', () => {
    expect(hitTest(box, { x: 150, y: 150 })).toBe(false)
  })

  it('accepts the boundary corners', () => {
    expect(hitTest(box, { x: 0,   y: 0   })).toBe(true)
    expect(hitTest(box, { x: 100, y: 100 })).toBe(true)
  })
})

// ── shapeBounds contract ──────────────────────────────────────────────────────

describe('shapeBounds', () => {
  it('handles a path shape', () => {
    const shapes = [
      { kind: 'path', points: [{ x: -10, y: 5 }, { x: 30, y: 5 }], width: 2 },
    ]
    const bb = shapeBounds(shapes)
    expect(bb).not.toBeNull()
    expect(bb.minX).toBe(-10)
    expect(bb.maxX).toBe(30)
  })
})
