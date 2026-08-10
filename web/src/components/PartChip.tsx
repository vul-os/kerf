import { X, Hash } from 'lucide-react'

interface Props {
  partId: string
  fileName?: string
  onRemove?: () => void
}

export default function PartChip({ partId, fileName, onRemove }: Props) {
  return (
    <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full bg-kerf-300/15 border border-kerf-300/40 text-kerf-100 text-[11px] font-mono max-w-full">
      <Hash size={10} className="flex-shrink-0 text-kerf-300" />
      <span className="truncate">{partId}</span>
      {fileName && <span className="text-ink-400">@{fileName}</span>}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          className="ml-0.5 text-ink-300 hover:text-kerf-200 flex-shrink-0 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/70"
          title="Remove"
        >
          <X size={10} />
        </button>
      )}
    </span>
  )
}
