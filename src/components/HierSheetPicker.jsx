// HierSheetPicker.jsx — hierarchical-schematic sub-sheet navigator
//
// Props:
//   circuitJson  — full circuit JSON (expected to contain board.sub_sheets)
//   onOpenSubSheet(fileId) — called when a row is clicked

export function getSubSheets(circuitJson) {
  return circuitJson?.board?.sub_sheets ?? []
}

export function getSubSheetDisplay(subSheet) {
  return {
    name: subSheet.name ?? 'Unnamed',
    sheetId: subSheet.sheet_id ?? subSheet.id ?? '',
    pinCount: Array.isArray(subSheet.pins) ? subSheet.pins.length : 0,
    fileId: subSheet.file_id ?? '',
  }
}

export default function HierSheetPicker({ circuitJson, onOpenSubSheet }) {
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