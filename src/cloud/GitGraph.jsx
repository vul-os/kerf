// GitGraph.jsx — SVG multi-lane commit graph.
//
// Props: { commits, branches, currentBranch, onCommitClick, selectedSha }
//
// Renders an SVG where each commit is a circle on a vertical lane; merges
// draw a Bézier curve linking lanes. Lane assignment is handled by the
// pure helper in src/lib/gitGraph.js (no DOM, fully testable).
//
// Below NARROW_PX the component falls back to a simple single-lane stack so
// the message column still has room to breathe.

import { useCallback, useLayoutEffect, useMemo, useRef, useState } from 'react'
import { GitMerge, Loader2 } from 'lucide-react'
import {
  assignLanes,
  edgePath,
  railX,
  ROW_H,
  RAIL_W,
  DOT_R,
  SIDE_PAD,
  NARROW_PX,
} from '../lib/gitGraph.js'

// ─── helpers ─────────────────────────────────────────────────────────────────

const shortSha = (s) => (s || '').slice(0, 7)

function relativeTime(iso) {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return ''
  const sec = Math.round((Date.now() - t) / 1000)
  if (sec < 45) return 'just now'
  const min = Math.round(sec / 60); if (min < 60) return `${min}m`
  const hr = Math.round(min / 60); if (hr < 24) return `${hr}h`
  const day = Math.round(hr / 24); if (day < 30) return `${day}d`
  const mo = Math.round(day / 30); if (mo < 12) return `${mo}mo`
  return `${Math.round(mo / 12)}y`
}

// ─── SVG rail renderer ────────────────────────────────────────────────────────

function GitGraphSVG({ rows, tips, railCount, commits, selectedSha, onPick }) {
  const width = SIDE_PAD * 2 + railCount * RAIL_W
  const height = rows.length * ROW_H
  const rowY = (i) => i * ROW_H + ROW_H / 2

  const rowOfSha = useMemo(() => {
    const m = new Map()
    commits.forEach((c, i) => { if (!m.has(c.sha)) m.set(c.sha, i) })
    return m
  }, [commits])

  const tipChips = []
  for (const t of tips) {
    if (!t.sha) continue
    const r = rowOfSha.get(t.sha)
    if (r === undefined) continue
    tipChips.push({ ...t, row: r })
  }

  return (
    <svg
      width={width}
      height={height}
      className="block shrink-0"
      style={{ minWidth: width }}
      aria-hidden="true"
    >
      {/* Edges */}
      {rows.map((row, i) => {
        const y0 = rowY(i)
        return row.parents.map((p, k) => {
          const parentRow = rowOfSha.get(commits[i].parent_shas?.[k])
          const y1 = parentRow !== undefined ? rowY(parentRow) : height + ROW_H
          const path = edgePath(row.rail, y0, p.rail, y1)
          return (
            <path
              key={`e-${i}-${k}`}
              d={path}
              stroke={p.color}
              strokeWidth={2}
              fill="none"
              strokeLinecap="round"
              opacity={0.92}
            />
          )
        })
      })}

      {/* Pass-through rail stubs */}
      {rows.map((row, i) => {
        const segments = []
        for (let j = 0; j < row.snapshot.length; j++) {
          const r = row.snapshot[j]
          if (!r || r.sha == null) continue
          if (j === row.rail) continue
          if (row.incomingRails.includes(j)) continue
          const x = railX(j)
          const y0 = i * ROW_H
          const y1 = (i + 1) * ROW_H
          segments.push(
            <line
              key={`s-${i}-${j}`}
              x1={x} y1={y0} x2={x} y2={y1}
              stroke={r.color}
              strokeWidth={2}
              opacity={0.92}
            />,
          )
        }
        return segments
      })}

      {/* Commit dots */}
      {rows.map((row, i) => {
        const c = commits[i]
        const cx = railX(row.rail)
        const cy = rowY(i)
        const isSelected = selectedSha === c.sha
        return (
          <g
            key={`d-${i}`}
            className="cursor-pointer"
            onClick={() => onPick(c.sha)}
            role="button"
            tabIndex={0}
            onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') onPick(c.sha) }}
            aria-label={`Commit ${shortSha(c.sha)}: ${(c.message || '').split('\n', 1)[0]}`}
          >
            <circle cx={cx} cy={cy} r={DOT_R + 1.5} fill="#0f1115" />
            <circle
              cx={cx} cy={cy} r={DOT_R}
              fill={row.isMerge ? '#0f1115' : row.color}
              stroke={row.color}
              strokeWidth={row.isMerge ? 2 : 1}
            />
            {isSelected && (
              <circle
                cx={cx} cy={cy} r={DOT_R + 3}
                fill="none"
                stroke={row.color}
                strokeWidth={1.25}
                opacity={0.7}
              />
            )}
            <title>
              {`${(c.sha || '').slice(0, 12)}\n${c.message || ''}\n${c.author_name || c.author || ''} · ${c.committed_at || ''}`}
            </title>
          </g>
        )
      })}

      {/* Branch tip chips */}
      {tipChips.map((t, i) => {
        const cx = railX(t.rail)
        const cy = rowY(t.row)
        const label = t.branch.toUpperCase()
        const padX = 5
        const charW = 5.4
        const chipW = Math.min(label.length * charW + padX * 2, 90)
        const chipH = 12
        return (
          <g key={`t-${i}`} transform={`translate(${cx + DOT_R + 4}, ${cy - chipH / 2})`}>
            <rect
              width={chipW} height={chipH} rx={3} ry={3}
              fill={t.color}
              opacity={0.18}
            />
            {t.isHead && (
              <rect
                width={chipW} height={chipH} rx={3} ry={3}
                fill="none"
                stroke={t.color}
                strokeWidth={1.5}
              />
            )}
            <text
              x={padX} y={chipH / 2 + 0.5}
              fontSize={9}
              dominantBaseline="middle"
              fill={t.color}
              style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', letterSpacing: 0.5 }}
            >
              {label.length * charW > chipW - padX * 2
                ? label.slice(0, Math.floor((chipW - padX * 2) / charW))
                : label}
            </text>
          </g>
        )
      })}
    </svg>
  )
}

// ─── Single-lane fallback ─────────────────────────────────────────────────────

function GraphRowSimple({ commit, isFirst, isLast, isSelected, onClick }) {
  const isMerge = (commit.parent_shas?.length || 0) > 1
  const title = (commit.message || '').split('\n', 1)[0] || '(no message)'
  return (
    <button
      type="button"
      onClick={onClick}
      className={
        'w-full flex items-stretch text-left focus:outline-none ' +
        (isSelected ? 'bg-ink-850/80' : 'hover:bg-ink-850/60 focus-visible:bg-ink-850')
      }
    >
      <div className="relative w-7 shrink-0">
        <div
          className="absolute left-1/2 -translate-x-px w-px bg-ink-700"
          style={{ top: isFirst ? '50%' : 0, bottom: isLast ? '50%' : 0 }}
        />
        <div
          className={
            'absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 grid place-items-center rounded-full ' +
            (isMerge
              ? 'w-3.5 h-3.5 bg-purple-500/20 border border-purple-400 text-purple-200'
              : 'w-2.5 h-2.5 bg-kerf-300 border border-kerf-200')
          }
        >
          {isMerge && <GitMerge size={8} />}
        </div>
      </div>
      <div className="flex-1 min-w-0 py-2 pr-2 border-b border-ink-850">
        <div className="flex items-center gap-2 min-w-0">
          <span className="text-[11px] text-ink-100 truncate flex-1">{title}</span>
          <span className="font-mono text-[10px] text-ink-500 shrink-0">{shortSha(commit.sha)}</span>
        </div>
        <div className="mt-0.5 flex items-center gap-2 text-[10px] text-ink-500 truncate">
          <span className="truncate">{commit.author_name || commit.author || ''}</span>
          {commit.committed_at && <span>· {relativeTime(commit.committed_at)}</span>}
          {isMerge && (
            <span className="px-1 rounded bg-purple-500/15 text-purple-300 uppercase tracking-wide text-[9px]">
              merge
            </span>
          )}
        </div>
      </div>
    </button>
  )
}

// ─── Public component ─────────────────────────────────────────────────────────
//
// Props:
//   commits       — array of commit objects (newest-first)
//   branches      — array of branch objects { name, head_sha, is_default }
//   currentBranch — active branch name (string)
//   loading       — boolean: show spinner when no commits yet
//   selectedSha   — externally controlled selection (string | null)
//   onCommitClick — (sha: string) => void
//
// The component owns NO selection state — the parent controls selectedSha and
// responds to onCommitClick.

export default function GitGraph({
  commits = [],
  branches = [],
  currentBranch = '',
  loading = false,
  selectedSha = null,
  onCommitClick,
}) {
  const wrapRef = useRef(null)
  const [narrow, setNarrow] = useState(false)

  useLayoutEffect(() => {
    const el = wrapRef.current
    if (!el || typeof ResizeObserver === 'undefined') return
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setNarrow(e.contentRect.width < NARROW_PX)
    })
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const layout = useMemo(
    () => assignLanes(commits, branches, currentBranch),
    [commits, branches, currentBranch],
  )

  const pick = useCallback((sha) => {
    onCommitClick?.(sha)
  }, [onCommitClick])

  if (loading && commits.length === 0) {
    return (
      <div ref={wrapRef} className="p-4 flex items-center gap-2 text-xs text-ink-400">
        <Loader2 size={14} className="animate-spin" /> Loading commits…
      </div>
    )
  }

  if (commits.length === 0) {
    return (
      <div ref={wrapRef} className="p-6 text-center text-xs text-ink-500">
        No commits yet — make the first one.
      </div>
    )
  }

  if (narrow) {
    return (
      <div ref={wrapRef}>
        <ul className="py-1">
          {commits.map((c, i) => (
            <li key={c.sha}>
              <GraphRowSimple
                commit={c}
                isFirst={i === 0}
                isLast={i === commits.length - 1}
                isSelected={selectedSha === c.sha}
                onClick={() => pick(c.sha)}
              />
            </li>
          ))}
        </ul>
      </div>
    )
  }

  const tooBusy = layout.railCount > 12

  return (
    <div ref={wrapRef}>
      {tooBusy && (
        <div className="mx-2 mt-2 mb-1 rounded-md border border-amber-500/30 bg-amber-500/10 px-2 py-1.5 text-[10px] text-amber-200/90 leading-snug">
          {layout.railCount} parallel branches detected — consider deleting
          merged branches to keep the graph readable.
        </div>
      )}
      <div className="flex items-stretch py-1">
        <div className="shrink-0">
          <GitGraphSVG
            rows={layout.rows}
            tips={layout.tips}
            railCount={Math.max(layout.railCount, 1)}
            commits={commits}
            selectedSha={selectedSha}
            onPick={pick}
          />
        </div>
        <ul className="flex-1 min-w-0">
          {commits.map((c, i) => {
            const title = (c.message || '').split('\n', 1)[0] || '(no message)'
            const isMerge = (c.parent_shas?.length || 0) > 1
            const isSelected = selectedSha === c.sha
            const fileCount = c.file_count != null ? c.file_count : null
            return (
              <li key={c.sha}>
                <button
                  type="button"
                  onClick={() => pick(c.sha)}
                  data-sha={c.sha}
                  className={
                    'w-full text-left px-2 flex flex-col justify-center focus:outline-none ' +
                    (isSelected
                      ? 'bg-ink-850/80'
                      : 'hover:bg-ink-850/60 focus-visible:bg-ink-850')
                  }
                  style={{ height: ROW_H }}
                >
                  <div className="flex items-center gap-2 min-w-0">
                    <span className="text-[11px] text-ink-100 truncate flex-1 leading-tight">
                      {title}
                    </span>
                    <span className="font-mono text-[10px] text-ink-500 shrink-0">
                      {shortSha(c.sha)}
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-[10px] text-ink-500 truncate leading-tight">
                    <span className="truncate">{c.author_name || c.author || ''}</span>
                    {c.committed_at && <span>· {relativeTime(c.committed_at)}</span>}
                    {fileCount != null && (
                      <span className="shrink-0">· {fileCount} file{fileCount !== 1 ? 's' : ''}</span>
                    )}
                    {isMerge && (
                      <span className="px-1 rounded bg-purple-500/15 text-purple-300 uppercase tracking-wide text-[9px]">
                        merge
                      </span>
                    )}
                  </div>
                </button>
              </li>
            )
          })}
        </ul>
      </div>
    </div>
  )
}
