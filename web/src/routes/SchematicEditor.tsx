// SchematicEditor.jsx — Route wrapper for the LTspice-equivalent schematic editor.
//
// Accessible at /schematic-editor

import SchematicEditorComponent from '../components/electronics/SchematicEditor.jsx'

export default function SchematicEditor() {
  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }}>
      <SchematicEditorComponent />
    </div>
  )
}
