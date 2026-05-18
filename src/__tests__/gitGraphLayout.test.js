// gitGraphLayout.test.js — unit tests for the pure graph-layout module.
//
// Pure no-DOM vitest. All tests exercise src/lib/gitGraph.js in isolation —
// no React, no SVG rendering, no fetch. The file-level comment in gitGraph.js
// documents the missing server-side `parent_shas` field; those code paths are
// tested here with synthetic fixtures so we're ready once the server lands it.
//
// Coverage:
//   1.  Empty repo / no commits / no branches
//   2.  Single-branch, single commit (root)
//   3.  Single-branch linear history (multiple commits, no parents)
//   4.  Single-branch with explicit parent_shas chain
//   5.  Two-branch divergence — separate tip SHAs
//   6.  Two-branch sharing the same head commit (fresh fork)
//   7.  Merge commit (two parents) spawns a second parent rail
//   8.  Lane colours — default branch is always LANE_COLORS[0]
//   9.  colorForBranch — non-default branches get a stable colour ≠ slot-0
//   10. hashStr — deterministic, non-negative, different for different strings
//   11. edgePath — straight for same rail, Bézier for different rails
//   12. railCount — never 0 for non-empty commits
//   13. tips — HEAD flag matches currentBranch argument
//   14. Branch list ordering — default branch is always rail 0
//   15. Orphan commits (no branch maps to them) land on a grey rail

import { describe, it, expect } from 'vitest'
import {
  assignLanes,
  colorForBranch,
  hashStr,
  edgePath,
  LANE_COLORS,
  ROW_H,
  RAIL_W,
  SIDE_PAD,
  railX,
} from '../lib/gitGraph.js'

// ─── Fixtures ────────────────────────────────────────────────────────────────

const mkCommit = (sha, message = 'msg', parentShas = []) => ({
  sha,
  message,
  parent_shas: parentShas,
  author_name: 'dev',
  created_at: new Date().toISOString(),
})

const mkBranch = (name, head_sha, is_default = false) => ({
  name,
  head_sha,
  is_default,
})

// ─── 1. Empty inputs ──────────────────────────────────────────────────────────

describe('assignLanes — empty inputs', () => {
  it('handles empty commits and branches', () => {
    const r = assignLanes([], [], '')
    expect(r.rows).toHaveLength(0)
    expect(r.tips).toHaveLength(0)
    expect(r.railCount).toBe(0)
    expect(r.defaultBranch).toBe('')
  })

  it('handles null/undefined gracefully', () => {
    const r = assignLanes(null, undefined, null)
    expect(r.rows).toHaveLength(0)
    expect(r.railCount).toBe(0)
  })

  it('handles commits with no branches', () => {
    const commits = [mkCommit('aaa')]
    const r = assignLanes(commits, [], '')
    expect(r.rows).toHaveLength(1)
    // Orphan → grey rail
    expect(r.rows[0].color).toBe(LANE_COLORS[7])
  })
})

// ─── 2. Single-branch, single commit (root) ───────────────────────────────────

describe('assignLanes — single root commit', () => {
  it('places the commit on rail 0', () => {
    const commits  = [mkCommit('abc')]
    const branches = [mkBranch('main', 'abc', true)]
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[0].rail).toBe(0)
  })

  it('assigns the default branch colour to rail 0', () => {
    const commits  = [mkCommit('abc')]
    const branches = [mkBranch('main', 'abc', true)]
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[0].color).toBe(LANE_COLORS[0])
  })

  it('tip has isHead=true when currentBranch matches', () => {
    const commits  = [mkCommit('abc')]
    const branches = [mkBranch('main', 'abc', true)]
    const r = assignLanes(commits, branches, 'main')
    expect(r.tips[0].isHead).toBe(true)
  })

  it('tip has isHead=false when currentBranch does not match', () => {
    const commits  = [mkCommit('abc')]
    const branches = [mkBranch('main', 'abc', true)]
    const r = assignLanes(commits, branches, 'feature')
    expect(r.tips[0].isHead).toBe(false)
  })

  it('railCount is at least 1', () => {
    const r = assignLanes([mkCommit('abc')], [mkBranch('main', 'abc', true)], 'main')
    expect(r.railCount).toBeGreaterThanOrEqual(1)
  })

  it('root commit has no parentRails (parents array empty)', () => {
    const r = assignLanes([mkCommit('abc')], [mkBranch('main', 'abc', true)], 'main')
    expect(r.rows[0].parents).toHaveLength(0)
  })
})

// ─── 3. Single-branch linear history, no explicit parent_shas ─────────────────
//  (Current server scenario: commits ordered newest-first, no parent links)

describe('assignLanes — linear history without parent_shas', () => {
  const commits  = ['c3', 'c2', 'c1'].map((sha) => mkCommit(sha))
  const branches = [mkBranch('main', 'c3', true)]

  it('all commits land on rail 0', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows.every((row) => row.rail === 0)).toBe(true)
  })

  it('row count matches commit count', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows).toHaveLength(3)
  })

  it('the head commit (index 0) gets the default-branch colour', () => {
    const r = assignLanes(commits, branches, 'main')
    // Only the branch-tip commit inherits the branch colour.
    // Older commits with no parent_shas linking them become orphans on grey.
    expect(r.rows[0].color).toBe(LANE_COLORS[0])
  })
})

// ─── 4. Single-branch with explicit parent_shas chain ─────────────────────────

describe('assignLanes — single branch with parent_shas', () => {
  // c3 → c2 → c1 (c1 is root)
  const commits  = [
    mkCommit('c3', 'third', ['c2']),
    mkCommit('c2', 'second', ['c1']),
    mkCommit('c1', 'first', []),
  ]
  const branches = [mkBranch('main', 'c3', true)]

  it('all commits land on rail 0', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows.every((row) => row.rail === 0)).toBe(true)
  })

  it('c3 has one parent pointing to rail 0', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[0].parents).toHaveLength(1)
    expect(r.rows[0].parents[0].rail).toBe(0)
  })

  it('c1 (root) has no parent rails', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[2].parents).toHaveLength(0)
  })
})

// ─── 5. Two-branch divergence (separate tip SHAs) ─────────────────────────────

describe('assignLanes — two branches diverged', () => {
  // main: m2 → m1
  // feat: f1  (branched from m1)
  const commits = [
    mkCommit('m2', 'main-tip', ['m1']),
    mkCommit('f1', 'feat-tip', ['m1']),
    mkCommit('m1', 'common',   []),
  ]
  const branches = [
    mkBranch('main', 'm2', true),
    mkBranch('feat', 'f1'),
  ]

  it('main tip is on rail 0, feat tip is on rail 1', () => {
    const r = assignLanes(commits, branches, 'main')
    const m2row = r.rows.find((_, i) => commits[i].sha === 'm2')
    const f1row = r.rows.find((_, i) => commits[i].sha === 'f1')
    expect(m2row.rail).toBe(0)
    expect(f1row.rail).toBe(1)
  })

  it('rail count is at least 2', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.railCount).toBeGreaterThanOrEqual(2)
  })

  it('feat tip colour differs from default branch colour', () => {
    const r = assignLanes(commits, branches, 'main')
    const f1row = r.rows.find((_, i) => commits[i].sha === 'f1')
    expect(f1row.color).not.toBe(LANE_COLORS[0])
  })

  it('tips array has exactly two entries', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.tips).toHaveLength(2)
  })
})

// ─── 6. Two branches sharing the same HEAD commit ─────────────────────────────

describe('assignLanes — two branches pointing at the same commit', () => {
  const commits  = [mkCommit('sha1', 'shared')]
  const branches = [
    mkBranch('main', 'sha1', true),
    mkBranch('feat', 'sha1'),
  ]

  it('does not crash', () => {
    expect(() => assignLanes(commits, branches, 'main')).not.toThrow()
  })

  it('the commit is placed on rail 0 (default branch wins)', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[0].rail).toBe(0)
  })

  it('both tips are emitted', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.tips).toHaveLength(2)
  })
})

// ─── 7. Merge commit (two parents) ────────────────────────────────────────────

describe('assignLanes — merge commit', () => {
  // merge → parent0 (main) AND parent1 (feat)
  const commits = [
    mkCommit('merge', 'Merge feat into main', ['main1', 'feat1']),
    mkCommit('main1', 'main commit', []),
    mkCommit('feat1', 'feat commit', []),
  ]
  const branches = [
    mkBranch('main', 'merge', true),
    mkBranch('feat', 'feat1'),
  ]

  it('merge row has isMerge=true', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[0].isMerge).toBe(true)
  })

  it('merge row has two parent rails', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[0].parents).toHaveLength(2)
  })

  it('non-merge rows have isMerge=false', () => {
    const r = assignLanes(commits, branches, 'main')
    expect(r.rows[1].isMerge).toBe(false)
    expect(r.rows[2].isMerge).toBe(false)
  })
})

// ─── 8. Lane colours — default branch ────────────────────────────────────────

describe('colorForBranch — default branch', () => {
  it('returns LANE_COLORS[0] for the default branch', () => {
    expect(colorForBranch('main', 'main')).toBe(LANE_COLORS[0])
    expect(colorForBranch('master', 'master')).toBe(LANE_COLORS[0])
  })

  it('returns LANE_COLORS[7] (grey) for empty name', () => {
    expect(colorForBranch('', 'main')).toBe(LANE_COLORS[7])
    expect(colorForBranch(null, 'main')).toBe(LANE_COLORS[7])
  })

  it('non-default branch does not get slot-0 colour', () => {
    expect(colorForBranch('feat', 'main')).not.toBe(LANE_COLORS[0])
  })
})

// ─── 9. colorForBranch — stability ───────────────────────────────────────────

describe('colorForBranch — deterministic', () => {
  it('same branch name always produces the same colour', () => {
    const c1 = colorForBranch('develop', 'main')
    const c2 = colorForBranch('develop', 'main')
    expect(c1).toBe(c2)
  })

  it('different branch names may produce different colours (or same by hash collision — just verify range)', () => {
    const c = colorForBranch('hotfix/auth', 'main')
    expect(LANE_COLORS).toContain(c)
  })
})

// ─── 10. hashStr ─────────────────────────────────────────────────────────────

describe('hashStr', () => {
  it('is deterministic', () => {
    expect(hashStr('hello')).toBe(hashStr('hello'))
  })

  it('returns a non-negative integer', () => {
    expect(hashStr('foo')).toBeGreaterThanOrEqual(0)
    expect(Number.isInteger(hashStr('foo'))).toBe(true)
  })

  it('empty string does not throw', () => {
    expect(() => hashStr('')).not.toThrow()
    expect(hashStr('')).toBe(0)
  })

  it('different strings produce different hashes (probabilistic; if this fails, collision is fine but worth noting)', () => {
    // These two are very unlikely to collide in the djb2 variant
    expect(hashStr('main')).not.toBe(hashStr('develop'))
  })
})

// ─── 11. edgePath ────────────────────────────────────────────────────────────

describe('edgePath', () => {
  it('produces a straight line when rail0 === rail1', () => {
    const p = edgePath(0, 0, 0, 28)
    expect(p).toMatch(/^M .* L /)
    expect(p).not.toMatch(/C /)
  })

  it('produces a cubic Bézier when rails differ', () => {
    const p = edgePath(0, 0, 1, 28)
    expect(p).toMatch(/^M .* C /)
  })

  it('starts at railX(rail0) and ends at railX(rail1)', () => {
    const x0 = railX(0)
    const x1 = railX(2)
    const p  = edgePath(0, 10, 2, 30)
    // Path must start with "M {x0} 10" and end at "{x1} 30"
    expect(p.startsWith(`M ${x0} 10`)).toBe(true)
    expect(p.endsWith(`${x1} 30`)).toBe(true)
  })
})

// ─── 12. railCount never 0 for non-empty history ─────────────────────────────

describe('railCount', () => {
  it('is at least 1 for a single commit', () => {
    const r = assignLanes([mkCommit('a')], [mkBranch('main', 'a', true)], 'main')
    expect(r.railCount).toBeGreaterThanOrEqual(1)
  })

  it('is 0 for completely empty input', () => {
    const r = assignLanes([], [], '')
    expect(r.railCount).toBe(0)
  })
})

// ─── 13. tips — HEAD flag ─────────────────────────────────────────────────────

describe('tips HEAD flag', () => {
  it('only the currentBranch tip has isHead=true', () => {
    const commits  = [mkCommit('c1'), mkCommit('c2')]
    const branches = [
      mkBranch('main', 'c1', true),
      mkBranch('feat', 'c2'),
    ]
    const r = assignLanes(commits, branches, 'feat')
    const mainTip = r.tips.find((t) => t.branch === 'main')
    const featTip = r.tips.find((t) => t.branch === 'feat')
    expect(mainTip.isHead).toBe(false)
    expect(featTip.isHead).toBe(true)
  })
})

// ─── 14. Branch ordering — default branch is always rail 0 ───────────────────

describe('branch ordering', () => {
  it('default branch is assigned rail 0 regardless of alpha ordering', () => {
    // 'zzz' would sort after 'main' alphabetically
    const branches = [
      mkBranch('zzz', 'z1'),
      mkBranch('main', 'm1', true),
    ]
    const commits  = [mkCommit('z1'), mkCommit('m1')]
    const r = assignLanes(commits, branches, 'main')
    const mainTip = r.tips.find((t) => t.branch === 'main')
    expect(mainTip.rail).toBe(0)
  })
})

// ─── 15. Orphan commits (no branch maps to them) ─────────────────────────────

describe('orphan commits', () => {
  it('commits not reachable from any branch tip land on a grey rail', () => {
    // Branch tip is 'aaa' but we include commit 'bbb' with no branch
    const commits  = [mkCommit('aaa'), mkCommit('bbb')]
    const branches = [mkBranch('main', 'aaa', true)]
    const r = assignLanes(commits, branches, 'main')
    const bbbRow = r.rows[1]
    expect(bbbRow.color).toBe(LANE_COLORS[7])
  })
})

// ─── Constants sanity ─────────────────────────────────────────────────────────

describe('layout constants', () => {
  it('ROW_H is 28', () => { expect(ROW_H).toBe(28) })
  it('RAIL_W is 18', () => { expect(RAIL_W).toBe(18) })
  it('SIDE_PAD is 10', () => { expect(SIDE_PAD).toBe(10) })
  it('LANE_COLORS has 8 entries', () => { expect(LANE_COLORS).toHaveLength(8) })
  it('railX(0) equals SIDE_PAD + RAIL_W/2', () => {
    expect(railX(0)).toBe(SIDE_PAD + RAIL_W / 2)
  })
  it('railX(1) equals SIDE_PAD + 1.5 * RAIL_W', () => {
    expect(railX(1)).toBe(SIDE_PAD + RAIL_W + RAIL_W / 2)
  })
})
