/**
 * CompareCategoryPill.jsx — horizontally scrollable pill row for compare categories.
 *
 * Props:
 *   categories  Array<{id, label}>   — ordered list from COMPARE_CATEGORIES
 *   active      string | null        — currently active category id (null = "All")
 *   onSelect    (id: string|null) => void
 */

interface Category {
  id: string
  label: string
}

interface Props {
  categories: Category[]
  active: string | null
  onSelect: (id: string | null) => void
}

export default function CompareCategoryPill({ categories, active, onSelect }: Props) {
  return (
    <div
      className="flex items-center gap-2 overflow-x-auto pb-1 scrollbar-hide"
      role="tablist"
      aria-label="Filter by CAD category"
    >
      {/* "All" pill */}
      <Pill
        id={null}
        label="All"
        active={active === null}
        onSelect={onSelect}
      />

      {categories.map((cat) => (
        <Pill
          key={cat.id}
          id={cat.id}
          label={cat.label}
          active={active === cat.id}
          onSelect={onSelect}
        />
      ))}
    </div>
  )
}

interface PillProps {
  id: string | null
  label: string
  active: boolean
  onSelect: (id: string | null) => void
}

/** Individual pill button. */
function Pill({ id, label, active, onSelect }: PillProps) {
  return (
    <button
      role="tab"
      aria-selected={active}
      data-category={id ?? 'all'}
      onClick={() => onSelect(active ? null : id)}
      className={[
        'shrink-0 rounded-full px-3.5 py-1.5 text-xs font-medium font-mono focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70',
        'border transition-colors focus-visible:outline focus-visible:outline-2',
        'focus-visible:outline-kerf-300 focus-visible:outline-offset-2',
        active
          ? 'border-kerf-300 bg-kerf-300/10 text-kerf-300'
          : 'border-ink-700 bg-ink-900/60 text-ink-400 hover:border-ink-500 hover:text-ink-200',
      ].join(' ')}
    >
      {label}
    </button>
  )
}
