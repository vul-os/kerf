/**
 * CategoryMatrix.jsx — horizontally-scrollable feature matrix that compares
 * every competitor in a category side-by-side against Kerf.
 *
 * Each row's cell values are derived from the per-CAD <CompareTable> data
 * on the individual /compare/<slug> pages — this component does not author
 * verdicts, it just lays them out compactly.
 *
 * Props:
 *   category    — short label, e.g. "Mechanical"; rendered in aria-label.
 *   competitors — [{ slug, label }] in display order (left of the Kerf column).
 *   features    — [{ group, name, cells: { [slug]: string, kerf: string } }]
 *                 cells are the same glyph-prefixed short strings used in
 *                 the per-CAD tables (e.g. "✅ FCC §15.109").
 *
 * Visuals deliberately mirror <CompareTable> in Freecad.jsx — same borders,
 * group sub-headers, alternating row tint, and font scale — so the hub feels
 * like part of the same comparison family.
 */
import { Link } from 'react-router-dom'
import { ArrowRight } from 'lucide-react'

export default function CategoryMatrix({ category, competitors, features }) {
  // Precompute group-header rows so we don't mutate state during render.
  const decorated = features.map((row, i) => ({
    row,
    index: i,
    showGroup: Boolean(row.group) && row.group !== features[i - 1]?.group,
  }))

  // Sized so each competitor column gets a comfortable text width even on
  // tiny phones — the wrapper handles horizontal scroll past 720px.
  const minWidth = 360 + competitors.length * 180 + 200 // feature col + comp cols + kerf

  return (
    <div className="-mx-6 sm:mx-0">
      <div
        className="overflow-x-auto rounded-none sm:rounded-xl border-y sm:border border-ink-800 bg-ink-950/40"
        role="region"
        aria-label={`${category} feature matrix`}
        tabIndex={0}
      >
        <table
          className="w-full text-sm"
          style={{ minWidth: `${minWidth}px` }}
          aria-label={`${category} CAD tools compared against Kerf, feature by feature`}
        >
          <thead>
            <tr className="border-b border-ink-800 bg-ink-900/70">
              <th
                scope="col"
                className="text-left px-4 py-3 font-mono text-[11px] uppercase tracking-wider text-ink-400 sticky left-0 bg-ink-900/95 backdrop-blur-sm z-10"
                style={{ minWidth: '220px' }}
              >
                Feature
              </th>
              {competitors.map((c) => (
                <th
                  key={c.slug}
                  scope="col"
                  className="text-left px-4 py-3 font-mono text-[11px] uppercase tracking-wider text-ink-300"
                  style={{ minWidth: '180px' }}
                >
                  <Link
                    to={`/compare/${c.slug}`}
                    className="inline-flex items-center gap-1.5 hover:text-ink-100 transition-colors group"
                    aria-label={`Deep-dive comparison: Kerf vs ${c.label}`}
                  >
                    {c.label}
                    <ArrowRight
                      size={11}
                      className="opacity-50 group-hover:opacity-100 group-hover:translate-x-0.5 transition-all"
                    />
                  </Link>
                </th>
              ))}
              <th
                scope="col"
                className="text-left px-4 py-3 font-mono text-[11px] uppercase tracking-wider text-kerf-300"
                style={{ minWidth: '200px' }}
              >
                Kerf
              </th>
            </tr>
          </thead>
          <tbody>
            {decorated.map(({ row, index, showGroup }) => (
              <MatrixRow
                key={row.name}
                row={row}
                index={index}
                showGroup={showGroup}
                competitors={competitors}
              />
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function MatrixRow({ row, index, showGroup, competitors }) {
  const colSpan = competitors.length + 2 // feature + comps + kerf
  return (
    <>
      {showGroup && (
        <tr className="bg-ink-900/70">
          <td
            colSpan={colSpan}
            className="px-4 py-2 font-mono text-[11px] uppercase tracking-[0.18em] text-kerf-300/80 border-b border-ink-800 sticky left-0"
          >
            {row.group}
          </td>
        </tr>
      )}
      <tr
        className={
          'border-b border-ink-800/50 transition-colors hover:bg-ink-900/30 ' +
          (index % 2 === 0 ? 'bg-transparent' : 'bg-ink-900/20')
        }
      >
        <th
          scope="row"
          className="px-4 py-3 text-ink-200 font-medium align-top text-left sticky left-0 bg-ink-950/90 backdrop-blur-sm"
          style={{ minWidth: '220px' }}
        >
          {row.name}
        </th>
        {competitors.map((c) => (
          <td
            key={c.slug}
            className="px-4 py-3 text-ink-300 align-top text-xs leading-relaxed"
          >
            {row.cells[c.slug] ?? <span className="text-ink-600">—</span>}
          </td>
        ))}
        <td className="px-4 py-3 text-ink-300 align-top text-xs leading-relaxed">
          {row.cells.kerf}
        </td>
      </tr>
    </>
  )
}
