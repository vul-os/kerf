// gitGraph.js — pure graph-layout module for the Git panel commit graph.
//
// No DOM, no React, no side-effects. Exports:
//   assignLanes(commits, branches, currentBranch) → { rows, tips, railCount, defaultBranch }
//   colorForBranch(name, defaultBranch) → hex string
//   edgePath(rail0, y0, rail1, y1) → SVG path string
//   hashStr(s) → int
//   LANE_COLORS, ROW_H, RAIL_W, DOT_R, SIDE_PAD, NARROW_PX
//
// SERVER NOTE (T-148): the /projects/{pid}/git/log endpoint (routes.py)
// returns {sha, message, author_name, author_email, created_at} — it does NOT
// include parent_shas or committed_at. The layout code below treats
// commit.parent_shas as optional (defaults to []). Until the server exposes
// parent relationships the graph renders single-lane chains ordered by
// created_at; merge edges will appear once the server adds parent_shas.

// ─── Layout constants ────────────────────────────────────────────────────────
export const ROW_H     = 28    // px per commit row
export const RAIL_W    = 18    // px per rail column
export const DOT_R     = 5     // commit dot radius
export const SIDE_PAD  = 10    // left padding inside the SVG before rail 0
export const NARROW_PX = 300   // below this, fall back to single-lane stack

// ─── Lane colour palette ─────────────────────────────────────────────────────
// Kerf-flavoured stable palette. First slot is reserved for the default
// branch (typically "main" / "master").
export const LANE_COLORS = [
  '#5BB0FF', // blue  — default branch
  '#6CD7B7', // teal
  '#E89A6F', // warm orange
  '#C896E8', // soft purple
  '#F0D86F', // amber
  '#7FE89A', // green
  '#E86F95', // pink
  '#9FA8B5', // cool grey
]

// ─── Utility helpers ─────────────────────────────────────────────────────────

// Cheap stable string hash. Used only for branch-name → palette index.
export function hashStr(s) {
  let h = 0
  for (let i = 0; i < s.length; i++) {
    h = ((h << 5) - h + s.charCodeAt(i)) | 0
  }
  return Math.abs(h)
}

// Pick a palette colour for a given branch name. The default branch always
// gets slot 0 (kerf blue); everything else hashes into slots 1..N.
export function colorForBranch(name, defaultBranch) {
  if (!name) return LANE_COLORS[7]
  if (defaultBranch && name === defaultBranch) return LANE_COLORS[0]
  const idx = 1 + (hashStr(name) % (LANE_COLORS.length - 1))
  return LANE_COLORS[idx]
}

// Project a rail index to the SVG x-coord (centre of the rail column).
export const railX = (rail) => SIDE_PAD + rail * RAIL_W + RAIL_W / 2

// Build an edge path from (rail0, y0) to (rail1, y1). Straight when rails
// match; otherwise a smooth cubic Bézier swoop.
export function edgePath(rail0, y0, rail1, y1) {
  const x0 = railX(rail0)
  const x1 = railX(rail1)
  if (rail0 === rail1) return `M ${x0} ${y0} L ${x1} ${y1}`
  const my = (y0 + y1) / 2
  return `M ${x0} ${y0} C ${x0} ${my}, ${x1} ${my}, ${x1} ${y1}`
}

// ─── Lane assignment ──────────────────────────────────────────────────────────
//
// Greedy top-down assignment. Given commits sorted newest-first and a branch
// list, walk rows top → bottom and place each commit on a rail:
//
//   1. Rails are seeded from branch HEADs. The default branch goes on rail 0;
//      remaining branches sort alphabetically for determinism.
//   2. For each commit:
//        a. It claims the leftmost rail currently mapped to its sha (if any).
//           When several branches converge on the same commit the leftmost
//           rail wins — matches the "default branch eats the merge point"
//           intuition users expect.
//        b. If no rail is mapped to it yet (ancestor outside the visible
//           window) it spawns a new rail at the right edge.
//        c. Its first parent inherits its rail.
//        d. Subsequent parents (merge commits) reuse an existing rail mapped
//           to that parent, or spawn a new one.
//   3. After each row we compact: rails whose expected sha doesn't appear in
//      the remaining commits are retired so we don't drag empty trails.
//
// Limitations (v1, not handled):
//   - Octopus merges (>2 parents): only the first two parents are wired.
//   - Pagination: lanes descending from commits below the 50-row window
//     terminate at the bottom of the visible graph.
//   - parent_shas absent (current server): graph renders as a single
//     ordered chain; merge edges appear once the server exposes parents.
//
// Returns: { rows, tips, railCount, defaultBranch }
//   rows[i]: { rail, color, branch, parents, isMerge, incomingRails, snapshot }
//   tips:    [{ sha, branch, isDefault, isHead, color, rail }]
//   railCount: max rail index seen (used to size the SVG)
//   defaultBranch: resolved default branch name (or '')
export function assignLanes(commits, branches, currentBranch) {
  const safeBranches = Array.isArray(branches) ? branches : []
  const safeCommits  = Array.isArray(commits)  ? commits  : []
  const defaultBranch = safeBranches.find((b) => b.is_default)?.name || ''

  // Stable branch ordering: default first, then alphabetical.
  const orderedBranches = [...safeBranches].sort((a, b) => {
    if (a.is_default) return -1
    if (b.is_default) return 1
    return a.name.localeCompare(b.name)
  })

  // Future-lookup: which row-index does each sha sit at? Used to retire dead
  // rails. When a sha appears more than once (shouldn't in practice) we keep
  // the first (earliest) occurrence.
  const rowOf = new Map()
  safeCommits.forEach((c, i) => { if (c.sha && !rowOf.has(c.sha)) rowOf.set(c.sha, i) })

  // rails[i] = { sha: <expected sha on this rail> | null, color, branch }
  // sha null = retired slot (kept to avoid shifting higher rails left).
  const rails = []
  const tips  = [] // { sha, branch, isDefault, isHead, color, rail }

  for (const b of orderedBranches) {
    const color = colorForBranch(b.name, defaultBranch)
    const rail  = rails.length
    rails.push({ sha: b.head_sha || null, color, branch: b.name })
    tips.push({
      sha:       b.head_sha,
      branch:    b.name,
      isDefault: !!b.is_default,
      isHead:    b.name === (currentBranch || ''),
      color,
      rail,
    })
  }

  // Allocate or reuse a rail for `sha`. Prefers leftmost existing match.
  const findRailFor = (sha) => {
    for (let i = 0; i < rails.length; i++) {
      if (rails[i]?.sha === sha) return i
    }
    return -1
  }
  const claimRail = (sha, color, branch) => {
    // Reuse a retired slot before extending.
    for (let i = 0; i < rails.length; i++) {
      if (rails[i]?.sha == null) {
        rails[i] = { sha, color, branch }
        return i
      }
    }
    rails.push({ sha, color, branch })
    return rails.length - 1
  }

  const rows = []

  for (let i = 0; i < safeCommits.length; i++) {
    const c       = safeCommits[i]
    const parents = Array.isArray(c.parent_shas) ? c.parent_shas : []

    // Snapshot of rail state at the *top* of this row (before we resolve the
    // commit). Used to draw pass-through stubs for rails that don't terminate.
    const snapshot = rails.map((r) => (r ? { ...r } : null))

    // 1. Find this commit's rail (leftmost match).
    let rail      = findRailFor(c.sha)
    let color     = rail >= 0 ? rails[rail].color : null
    let branchName= rail >= 0 ? rails[rail].branch : null

    if (rail < 0) {
      // Orphan: older than every branch tip we know, or below the window.
      color      = LANE_COLORS[7]
      branchName = ''
      rail       = claimRail(c.sha, color, branchName)
    }

    // 2. Collapse sibling rails that also point to this commit.
    const incomingRails = [rail]
    for (let j = 0; j < rails.length; j++) {
      if (j === rail) continue
      if (rails[j]?.sha === c.sha) {
        incomingRails.push(j)
        rails[j] = { sha: null, color: rails[j].color, branch: rails[j].branch }
      }
    }

    // 3. Wire up parents.
    const parentRails = []
    if (parents.length === 0) {
      // Root commit — rail terminates.
      rails[rail] = { sha: null, color, branch: branchName }
    } else {
      // First parent inherits this rail.
      rails[rail] = { sha: parents[0], color, branch: branchName }
      parentRails.push({ rail, color })

      // Second parent (merge): reuse or spawn.
      if (parents.length >= 2) {
        let pRail = findRailFor(parents[1])
        if (pRail < 0) {
          pRail = claimRail(parents[1], LANE_COLORS[rails.length % LANE_COLORS.length], '')
        }
        parentRails.push({ rail: pRail, color: rails[pRail].color })
      }
    }

    // 4. Compact: retire rails whose expected sha is no longer in the set.
    for (let j = 0; j < rails.length; j++) {
      const r = rails[j]
      if (r?.sha && !rowOf.has(r.sha)) {
        rails[j] = { sha: null, color: r.color, branch: r.branch }
      }
    }
    // Trim trailing retired slots so SVG width stays tight.
    while (rails.length && rails[rails.length - 1]?.sha == null) {
      rails.pop()
    }

    rows.push({
      rail, color, branch: branchName,
      parents:       parentRails,
      isMerge:       parents.length >= 2,
      incomingRails,
      snapshot,
    })
  }

  // Width budget: high-water mark of rail indices seen during the walk.
  let railCount = 0
  for (const r of rows) {
    railCount = Math.max(railCount, r.snapshot.length, r.rail + 1)
    for (const p of r.parents) railCount = Math.max(railCount, p.rail + 1)
  }

  return { rows, tips, railCount, defaultBranch }
}
