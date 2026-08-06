// HierSheetPicker.tsx — hierarchical-schematic sub-sheet navigator
//
// Props:
//   circuitJson  — wrapper object with a `board.sub_sheets` array (the
//                  CircuitJSON `pcb_board` extension described in
//                  src/lib/hierSchematic.ts), not the raw CircuitJson array.
//   onOpenSubSheet(fileId) — called when a row is clicked

export interface SubSheet {
  id?: string
  name?: string
  sheet_id?: string
  file_id?: string
  position?: [number, number]
  pins?: unknown[]
}

export interface HierCircuitJson {
  board?: {
    sub_sheets?: SubSheet[]
  }
}

export interface SubSheetDisplay {
  name: string
  sheetId: string
  pinCount: number
  fileId: string
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helpers consumed directly by tests; not components
export function getSubSheets(circuitJson?: HierCircuitJson | null): SubSheet[] {
  return circuitJson?.board?.sub_sheets ?? []
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helpers consumed directly by tests; not components
export function getSubSheetDisplay(subSheet: SubSheet): SubSheetDisplay {
  return {
    name: subSheet.name ?? 'Unnamed',
    sheetId: subSheet.sheet_id ?? subSheet.id ?? '',
    pinCount: Array.isArray(subSheet.pins) ? subSheet.pins.length : 0,
    fileId: subSheet.file_id ?? '',
  }
}

export interface HierSheetPickerProps {
  circuitJson?: HierCircuitJson | null
  onOpenSubSheet?: (fileId: string) => void
}

export default function HierSheetPicker({ circuitJson, onOpenSubSheet }: HierSheetPickerProps) {
  const subSheets = getSubSheets(circuitJson)

  if (subSheets.length === 0) {
    return (
      <div className="hier-sheet-picker hier-sheet-picker--empty" data-testid="hier-sheet-picker">
        <span className="hier-sheet-picker__empty-msg">No sub-sheets</span>
      </div>
    )
  }

  return (
    <div className="hier-sheet-picker" data-testid="hier-sheet-picker">
      <div className="hier-sheet-picker__header">
        <span>Sub-sheets</span>
        <span>{subSheets.length}</span>
      </div>
      <ul className="hier-sheet-picker__list">
        {subSheets.map((sheet) => {
          const { name, sheetId, pinCount, fileId } = getSubSheetDisplay(sheet)
          return (
            <li
              key={fileId || sheetId}
              className="hier-sheet-picker__row"
              onClick={() => onOpenSubSheet?.(fileId)}
              role="button"
              tabIndex={0}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault()
                  onOpenSubSheet?.(fileId)
                }
              }}
            >
              <span className="hier-sheet-picker__name">{name}</span>
              <span className="hier-sheet-picker__meta">
                <span className="hier-sheet-picker__sheet-id">{sheetId}</span>
                <span className="hier-sheet-picker__pin-count">{pinCount} pins</span>
              </span>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
