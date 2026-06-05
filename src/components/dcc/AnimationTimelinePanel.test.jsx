/**
 * AnimationTimelinePanel.test.jsx
 * ================================
 * Tests for the DCC Animation Timeline panel.
 *
 * Strategy
 * --------
 * Tier 1 — source inspection: data-testid landmarks, tool call presence.
 * Tier 2 — renderToStaticMarkup smoke tests: mounts, controls present.
 * Tier 3 — exported pure-helper unit tests: makeIKArgs, makeApplyPoseArgs,
 *           makeEvaluateClipArgs (directly testable without DOM).
 * Tier 4 — client logic: DEFAULT_CLIP / DEFAULT_BONES shape + keyframe helpers.
 */

import { describe, it, expect, vi } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import path from 'path'
import { renderToStaticMarkup } from 'react-dom/server'

const __dirname = path.dirname(fileURLToPath(import.meta.url))
const src = readFileSync(path.resolve(__dirname, './AnimationTimelinePanel.jsx'), 'utf8')

// ── Mocks ─────────────────────────────────────────────────────────────────────

vi.mock('lucide-react', () => {
  const Stub = () => null
  return {
    Play: Stub, Pause: Stub, SkipBack: Stub, SkipForward: Stub,
    Plus: Stub, Trash2: Stub, Activity: Stub, ChevronDown: Stub,
    ChevronRight: Stub, Zap: Stub,
  }
})

import AnimationTimelinePanel, {
  DEFAULT_CLIP,
  DEFAULT_BONES,
  makeIKArgs,
  makeApplyPoseArgs,
  makeEvaluateClipArgs,
} from './AnimationTimelinePanel.jsx'

// ── Source inspection ─────────────────────────────────────────────────────────

describe('AnimationTimelinePanel source: required testids and tool calls', () => {
  it('has data-testid="animation-timeline-panel"', () => {
    expect(src).toContain('data-testid="animation-timeline-panel"')
  })

  it('calls animation_evaluate_clip', () => {
    expect(src).toContain('animation_evaluate_clip')
  })

  it('calls animation_solve_ik', () => {
    expect(src).toContain('animation_solve_ik')
  })

  it('calls animation_apply_pose', () => {
    expect(src).toContain('animation_apply_pose')
  })

  it('has scrub-slider testid', () => {
    expect(src).toContain('data-testid="scrub-slider"')
  })

  it('has btn-play-pause testid', () => {
    expect(src).toContain('data-testid="btn-play-pause"')
  })

  it('has btn-solve-ik testid', () => {
    expect(src).toContain('data-testid="btn-solve-ik"')
  })

  it('has btn-add-keyframe testid', () => {
    expect(src).toContain('data-testid="btn-add-keyframe"')
  })

  it('has fcurve-chart testid (SVG)', () => {
    expect(src).toContain('data-testid="fcurve-chart"')
  })

  it('has keyframe-list testid', () => {
    expect(src).toContain('data-testid="keyframe-list"')
  })

  it('has ik-enabled-toggle testid', () => {
    expect(src).toContain('data-testid="ik-enabled-toggle"')
  })

  it('dispatches ANIM_IK_SOLVED', () => {
    expect(src).toContain('ANIM_IK_SOLVED')
  })

  it('dispatches ANIM_POSE_APPLIED', () => {
    expect(src).toContain('ANIM_POSE_APPLIED')
  })

  it('dispatches ANIM_CLIP_EVALUATED', () => {
    expect(src).toContain('ANIM_CLIP_EVALUATED')
  })
})

// ── Exported defaults ─────────────────────────────────────────────────────────

describe('DEFAULT_CLIP', () => {
  it('has name, duration, fcurves', () => {
    expect(typeof DEFAULT_CLIP.name).toBe('string')
    expect(typeof DEFAULT_CLIP.duration).toBe('number')
    expect(typeof DEFAULT_CLIP.fcurves).toBe('object')
  })

  it('has at least one fcurve channel', () => {
    expect(Object.keys(DEFAULT_CLIP.fcurves).length).toBeGreaterThan(0)
  })

  it('each channel has at least 2 keyframes', () => {
    for (const kfs of Object.values(DEFAULT_CLIP.fcurves)) {
      expect(Array.isArray(kfs)).toBe(true)
      expect(kfs.length).toBeGreaterThanOrEqual(2)
    }
  })

  it('keyframes have t and value', () => {
    for (const kfs of Object.values(DEFAULT_CLIP.fcurves)) {
      for (const kf of kfs) {
        expect(typeof kf.t).toBe('number')
        expect(kf.value !== undefined).toBe(true)
      }
    }
  })
})

describe('DEFAULT_BONES', () => {
  it('is an array of at least 2 bones', () => {
    expect(Array.isArray(DEFAULT_BONES)).toBe(true)
    expect(DEFAULT_BONES.length).toBeGreaterThanOrEqual(2)
  })

  it('every bone has name, head, tail', () => {
    for (const b of DEFAULT_BONES) {
      expect(typeof b.name).toBe('string')
      expect(Array.isArray(b.head)).toBe(true)
      expect(Array.isArray(b.tail)).toBe(true)
    }
  })
})

// ── SSR smoke tests ───────────────────────────────────────────────────────────

describe('AnimationTimelinePanel renderToStaticMarkup', () => {
  it('mounts without throwing', () => {
    expect(() => renderToStaticMarkup(<AnimationTimelinePanel />)).not.toThrow()
  })

  it('renders animation-timeline-panel root', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('animation-timeline-panel')
  })

  it('renders scrub slider', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('scrub-slider')
  })

  it('renders play-pause button', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('btn-play-pause')
  })

  it('renders fcurve-chart SVG', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('fcurve-chart')
  })

  it('renders keyframe-list', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('keyframe-list')
  })

  it('renders IK toggle', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('ik-enabled-toggle')
  })

  it('renders IK algorithm buttons', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('ik-algo-ccd')
    expect(html).toContain('ik-algo-fabrik')
  })

  it('renders bone rows for DEFAULT_BONES', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    for (const b of DEFAULT_BONES) {
      expect(html).toContain(`bone-row-${b.name}`)
    }
  })

  it('accepts content prop with clip JSON', () => {
    const content = JSON.stringify(DEFAULT_CLIP)
    expect(() => renderToStaticMarkup(<AnimationTimelinePanel content={content} />)).not.toThrow()
  })

  it('handles bad content gracefully', () => {
    expect(() => renderToStaticMarkup(<AnimationTimelinePanel content="NOT_JSON" />)).not.toThrow()
  })

  it('renders interp buttons in add-keyframe section', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('interp-step')
    expect(html).toContain('interp-linear')
    expect(html).toContain('interp-bezier')
  })

  it('renders skip-back and skip-forward buttons', () => {
    const html = renderToStaticMarkup(<AnimationTimelinePanel />)
    expect(html).toContain('btn-skip-back')
    expect(html).toContain('btn-skip-forward')
  })
})

// ── Exported pure-helper unit tests ──────────────────────────────────────────

describe('makeIKArgs — animation_solve_ik arg shape', () => {
  it('is a function', () => {
    expect(typeof makeIKArgs).toBe('function')
  })

  it('returns bones, chain, target, algorithm', () => {
    const args = makeIKArgs({
      bones: DEFAULT_BONES,
      ikTarget: [0, 1.5, 0],
      ikAlgorithm: 'fabrik',
    })
    expect(args).toHaveProperty('bones')
    expect(args).toHaveProperty('chain')
    expect(args).toHaveProperty('target')
    expect(args).toHaveProperty('algorithm')
    expect(Array.isArray(args.bones)).toBe(true)
    expect(Array.isArray(args.chain)).toBe(true)
    expect(args.chain.length).toBe(DEFAULT_BONES.length)
    expect(args.algorithm).toBe('fabrik')
  })

  it('chain is derived from bones names', () => {
    const args = makeIKArgs({
      bones: DEFAULT_BONES,
      ikTarget: [0, 2, 0],
      ikAlgorithm: 'ccd',
    })
    const boneNames = DEFAULT_BONES.map((b) => b.name)
    expect(args.chain).toEqual(boneNames)
    expect(args.algorithm).toBe('ccd')
  })

  it('target matches input', () => {
    const target = [1, 2, 0.5]
    const args = makeIKArgs({ bones: DEFAULT_BONES, ikTarget: target, ikAlgorithm: 'fabrik' })
    expect(args.target).toEqual(target)
  })
})

describe('makeApplyPoseArgs — animation_apply_pose arg shape', () => {
  it('is a function', () => {
    expect(typeof makeApplyPoseArgs).toBe('function')
  })

  it('returns bones and rotations', () => {
    const rotations = { root: [[1,0,0],[0,1,0],[0,0,1]] }
    const args = makeApplyPoseArgs({ bones: DEFAULT_BONES, rotations })
    expect(args).toHaveProperty('bones')
    expect(args).toHaveProperty('rotations')
    expect(args.rotations).toEqual(rotations)
    expect(Array.isArray(args.bones)).toBe(true)
  })
})

describe('makeEvaluateClipArgs — animation_evaluate_clip arg shape', () => {
  it('is a function', () => {
    expect(typeof makeEvaluateClipArgs).toBe('function')
  })

  it('returns name, duration, fcurves, eval_time', () => {
    const args = makeEvaluateClipArgs({ clip: DEFAULT_CLIP, evalTime: 0.5 })
    expect(args).toHaveProperty('name')
    expect(args).toHaveProperty('duration')
    expect(args).toHaveProperty('fcurves')
    expect(args).toHaveProperty('eval_time')
    expect(args.eval_time).toBe(0.5)
    expect(args.name).toBe(DEFAULT_CLIP.name)
    expect(args.duration).toBe(DEFAULT_CLIP.duration)
  })

  it('passes fcurves through unchanged', () => {
    const args = makeEvaluateClipArgs({ clip: DEFAULT_CLIP, evalTime: 1.0 })
    expect(args.fcurves).toBe(DEFAULT_CLIP.fcurves)
  })
})
