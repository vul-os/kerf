// Pmi3DOverlay.tsx — 3D PMI (Product and Manufacturing Information) overlay.
//
// Renders FCF callouts and datum labels as HTML overlays positioned in screen
// space over the three.js canvas. Uses a Three.js Vector3 → screen projection
// at each frame so the labels follow the model as it orbits.
//
// Usage (inside the Renderer's return JSX, or as a sibling):
//
//   <Pmi3DOverlay
//     annotations={pmiAnnotations}        // FCF / datum objects from the drawing
//     threeState={stateRef.current}        // Renderer's stateRef (camera, renderer)
//     onPick={handlePick}                  // optional: called when label clicked
//     activeTool={pmiTool}                 // 'gdt:fcf:*' | 'gdt:datum:*' | null
//     onPlace={handlePlace}                // called with { worldPos, faceId } on click
//   />
//
// The overlay also handles the click-to-place cursor stencil: when `activeTool`
// is set the cursor becomes a crosshair and clicking emits `onPlace`.

import { useCallback, useEffect, useRef, useState } from 'react'
import type * as ThreeNS from 'three'
import { renderFcf, GDT_SYMBOL_MAP } from '../lib/gdntAnnotations.js'

// ── Types ──────────────────────────────────────────────────────────────────────
//
// KNOWN BUG (report, not fix — see T-513 migration report): both `project()` and
// `handleCanvasClick()` below read `window.__THREE__`, but nothing in this
// codebase ever assigns it — grepped the full src/ tree, including Renderer.jsx,
// which the inline comment claims caches it there. It doesn't. That means `THREE`
// is always `undefined` at runtime, so both functions hit their `if (!THREE)
// return` guard on every call: `project()` never populates `positions`, which
// means any annotation that HAS a `world_pos` (the normal 3D-anchored case) always
// renders with `visible = false` per the fallback logic below and never appears;
// only annotations without a world anchor show, at the fixed list fallback
// position. `handleCanvasClick` likewise always no-ops, so GD&T click-to-place
// never fires `onPlace`. Preserved exactly as-is (no behavior change) — worth a
// real look from whoever owns PMI/GD&T next.

export interface GdtDatumRef {
  label: string
  modifier?: string | null
}

export interface PmiFcfAnnotation {
  id: string
  kind: 'fcf'
  symbol_code: string
  tolerance_value?: number
  diameter_zone?: boolean
  tolerance_modifier?: string
  datum_refs?: GdtDatumRef[]
  rendered?: string
  world_pos?: { x: number; y: number; z: number } | null
}

export interface PmiDatumAnnotation {
  id: string
  kind: 'gdt_datum'
  label: string
  world_pos?: { x: number; y: number; z: number } | null
}

/** Other annotation kinds pass through this overlay untouched (filtered out before render). */
export interface PmiOtherAnnotation {
  id: string
  kind: string
  world_pos?: { x: number; y: number; z: number } | null
}

export type PmiAnnotation = PmiFcfAnnotation | PmiDatumAnnotation | PmiOtherAnnotation

/**
 * Renderer.jsx's stateRef shape, as far as this overlay reads it. Three.js itself
 * has no usable types in this repo (no @types/three, no shipped .d.ts — see the
 * prior T-513 commits), so these member types resolve to `any` regardless.
 */
export interface PmiThreeState {
  camera?: ThreeNS.Camera
  renderer?: ThreeNS.WebGLRenderer
  scene?: ThreeNS.Scene
}

interface ScreenPos {
  x: number
  y: number
  visible: boolean
}

export interface Pmi3DOverlayProps {
  annotations?: PmiAnnotation[]
  threeState?: PmiThreeState | null
  selectedId?: string | null
  onPick?: (ann: PmiAnnotation) => void
  activeTool?: string | null
  onPlace?: (placement: { worldPos: { x: number; y: number; z: number }; faceId: string | null }) => void
}

// ---------------------------------------------------------------------------
// FcfLabel — a single FCF rendered as a styled HTML chip.

function FcfLabel({ ann, x, y, selected, onClick }: { ann: PmiFcfAnnotation; x: number; y: number; selected: boolean; onClick?: (ann: PmiAnnotation) => void }) {
  const sym = GDT_SYMBOL_MAP[ann.symbol_code]
  const rendered = ann.rendered || renderFcf(ann)
  const diaStr = ann.diameter_zone ? '⌀' : ''
  const modMap: Record<string, string> = { M: 'Ⓜ', L: 'Ⓛ', S: 'Ⓢ', F: 'Ⓕ', P: 'Ⓟ', T: 'Ⓣ' }
  const modStr = ann.tolerance_modifier ? ` ${modMap[ann.tolerance_modifier] || ann.tolerance_modifier}` : ''
  const datums = (ann.datum_refs || []).map((d) => d.label)

  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`FCF: ${rendered}`}
      data-testid={`pmi-fcf-${ann.id}`}
      onClick={() => onClick?.(ann)}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.(ann)}
      className={`absolute pointer-events-auto select-none cursor-pointer transition-shadow
        ${selected ? 'ring-2 ring-kerf-300 shadow-kerf-300/30' : 'hover:ring-1 hover:ring-ink-500'}`}
      style={{ left: x, top: y, transform: 'translate(-50%, -50%)' }}
    >
      {/* ISO 1101 feature-control-frame: | symbol | tol | datum... | */}
      <div className="flex h-6 rounded border border-ink-600 overflow-hidden shadow-md bg-white text-ink-950 text-[10px] font-mono leading-none">
        {/* Symbol compartment */}
        <div className="flex items-center justify-center w-7 border-r border-ink-400 bg-gray-50 text-[14px]">
          {sym?.unicode || '?'}
        </div>
        {/* Tolerance compartment */}
        <div className="flex items-center px-1.5 border-r border-ink-400 whitespace-nowrap min-w-[2.5rem]">
          {diaStr}{ann.tolerance_value}{modStr}
        </div>
        {/* Datum compartments */}
        {datums.map((d, i) => (
          <div key={i} className="flex items-center px-1.5 border-r border-ink-400 last:border-r-0 font-bold">
            {d}
          </div>
        ))}
      </div>
      {/* Leader dot */}
      <div className="absolute left-1/2 -bottom-1 -translate-x-1/2 w-1.5 h-1.5 rounded-full bg-ink-500" />
    </div>
  )
}

// ---------------------------------------------------------------------------
// DatumLabel — datum triangle + letter.

function DatumLabel({ ann, x, y, selected, onClick }: { ann: PmiDatumAnnotation; x: number; y: number; selected: boolean; onClick?: (ann: PmiAnnotation) => void }) {
  return (
    <div
      role="button"
      tabIndex={0}
      aria-label={`Datum ${ann.label}`}
      data-testid={`pmi-datum-${ann.id}`}
      onClick={() => onClick?.(ann)}
      onKeyDown={(e) => e.key === 'Enter' && onClick?.(ann)}
      className={`absolute pointer-events-auto select-none cursor-pointer transition-shadow
        ${selected ? 'ring-2 ring-kerf-300 shadow-kerf-300/30' : 'hover:ring-1 hover:ring-ink-500'}`}
      style={{ left: x, top: y, transform: 'translate(-50%, -50%)' }}
    >
      <div className="flex items-center justify-center w-7 h-7 rounded-sm border-2 border-ink-700 bg-white text-ink-950 text-[13px] font-bold font-mono shadow-md">
        {ann.label}
      </div>
      {/* Triangle pointer */}
      <div
        className="absolute left-1/2 -bottom-2.5 -translate-x-1/2"
        style={{
          width: 0,
          height: 0,
          borderLeft: '5px solid transparent',
          borderRight: '5px solid transparent',
          borderTop: '10px solid #374151',
        }}
      />
    </div>
  )
}

// ---------------------------------------------------------------------------
// Pmi3DOverlay — main component.

export default function Pmi3DOverlay({
  annotations = [],
  threeState = null,
  selectedId = null,
  onPick,
  activeTool = null,
  onPlace,
}: Pmi3DOverlayProps) {
  const containerRef = useRef<HTMLDivElement | null>(null)
  const [positions, setPositions] = useState<Map<string, ScreenPos>>(new Map())
  const rafRef = useRef<number | null>(null)

  // Project world-space positions to screen coords on every animation frame.
  // We avoid re-rendering on every frame by comparing old positions.
  const project = useCallback(() => {
    const s = threeState
    if (!s || !s.camera || !s.renderer || !containerRef.current) return

    const { camera, renderer } = s
    const domEl = renderer.domElement
    const rect = domEl.getBoundingClientRect()
    const containerRect = containerRef.current.getBoundingClientRect()
    if (rect.width === 0 || rect.height === 0) return

    // See the KNOWN BUG note above: this is always undefined at runtime.
    const THREE = (window as unknown as { __THREE__?: typeof ThreeNS }).__THREE__ // cached by Renderer.jsx — fallback to import
    if (!THREE) return

    const next = new Map<string, ScreenPos>()
    for (const ann of annotations) {
      if (ann.kind !== 'fcf' && ann.kind !== 'gdt_datum') continue
      if (ann.world_pos == null) continue // no 3D anchor yet

      const v = new THREE.Vector3(ann.world_pos.x, ann.world_pos.y, ann.world_pos.z)
      v.project(camera)

      // NDC → pixel coords relative to renderer canvas.
      const px = (v.x * 0.5 + 0.5) * rect.width + rect.left - containerRect.left
      const py = (-(v.y * 0.5) + 0.5) * rect.height + rect.top - containerRect.top

      // Cull when behind camera (z > 1) or outside viewport.
      const visible = v.z < 1 && px >= 0 && px <= rect.width && py >= 0 && py <= rect.height
      next.set(ann.id, { x: px, y: py, visible })
    }

    setPositions((prev) => {
      // Avoid setState if nothing changed.
      let changed = prev.size !== next.size
      if (!changed) {
        for (const [id, pos] of next) {
          const old = prev.get(id)
          if (!old || Math.abs(old.x - pos.x) > 0.5 || Math.abs(old.y - pos.y) > 0.5 || old.visible !== pos.visible) {
            changed = true
            break
          }
        }
      }
      return changed ? next : prev
    })
  }, [annotations, threeState])

  useEffect(() => {
    let alive = true
    function loop() {
      if (!alive) return
      project()
      rafRef.current = requestAnimationFrame(loop)
    }
    rafRef.current = requestAnimationFrame(loop)
    return () => {
      alive = false
      if (rafRef.current) cancelAnimationFrame(rafRef.current)
    }
  }, [project])

  // Click-to-place handler. When activeTool is set, clicking on the 3D
  // canvas emits onPlace with the cursor position and nearest face id.
  const handleCanvasClick = useCallback((e: MouseEvent) => {
    if (!activeTool || !onPlace) return
    const s = threeState
    if (!s || !s.camera || !s.renderer || !s.scene) return

    // See the KNOWN BUG note above: this is always undefined at runtime.
    const THREE = (window as unknown as { __THREE__?: typeof ThreeNS }).__THREE__
    if (!THREE) return

    const rect = s.renderer.domElement.getBoundingClientRect()
    const ndcX = ((e.clientX - rect.left) / rect.width) * 2 - 1
    const ndcY = -((e.clientY - rect.top) / rect.height) * 2 + 1

    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera({ x: ndcX, y: ndcY } as ThreeNS.Vector2, s.camera)

    // Collect all meshes in the scene for intersection.
    const meshes: ThreeNS.Object3D[] = []
    s.scene.traverse((obj) => {
      if ((obj as ThreeNS.Mesh).isMesh) meshes.push(obj)
    })
    const hits = raycaster.intersectObjects(meshes, false)
    if (hits.length === 0) return

    const hit = hits[0]
    const worldPos = hit.point.clone()
    const faceId = (hit.object?.userData?.faceId as string | undefined) || hit.object?.name || null

    onPlace({ worldPos: { x: worldPos.x, y: worldPos.y, z: worldPos.z }, faceId })
  }, [activeTool, onPlace, threeState])

  // Wire click listener to the renderer canvas.
  useEffect(() => {
    if (!activeTool || !threeState?.renderer) return
    const canvas = threeState.renderer.domElement
    canvas.addEventListener('click', handleCanvasClick)
    return () => canvas.removeEventListener('click', handleCanvasClick)
  }, [activeTool, handleCanvasClick, threeState])

  return (
    <div
      ref={containerRef}
      className={`absolute inset-0 pointer-events-none z-20 ${activeTool ? 'cursor-crosshair' : ''}`}
      data-testid="pmi-3d-overlay"
    >
      {annotations.map((ann) => {
        if (ann.kind !== 'fcf' && ann.kind !== 'gdt_datum') return null
        const pos = positions.get(ann.id)
        // If no world_pos (2D-only annotation), render at a fixed position
        // in the top-left quadrant so the user can still see it.
        const x = pos?.x ?? 20
        const y = pos?.y ?? (20 + annotations.indexOf(ann) * 30)
        const visible = pos ? pos.visible : (ann.world_pos == null)

        if (!visible) return null

        if (ann.kind === 'fcf') {
          return (
            <FcfLabel
              key={ann.id}
              // PmiOtherAnnotation's `kind: string` is too wide for TS to exclude via the
              // `ann.kind === 'fcf'` check above; the runtime discriminant already guarantees
              // this is a PmiFcfAnnotation.
              ann={ann as PmiFcfAnnotation}
              x={x}
              y={y}
              selected={ann.id === selectedId}
              onClick={onPick}
            />
          )
        }
        if (ann.kind === 'gdt_datum') {
          return (
            <DatumLabel
              key={ann.id}
              ann={ann as PmiDatumAnnotation}
              x={x}
              y={y}
              selected={ann.id === selectedId}
              onClick={onPick}
            />
          )
        }
        return null
      })}
    </div>
  )
}
