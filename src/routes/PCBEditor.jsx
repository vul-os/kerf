// PCBEditor.jsx — Route wrapper for the interactive PCB editor.
//
// Accessible at /pcb-editor (optionally with ?project_id=<id> to load
// a real board from the backend; without it a mock demo fixture is shown).

import PCBInteractiveEditor from '../components/electronics/PCBInteractiveEditor.jsx'

export default function PCBEditor() {
  return (
    <div style={{ height: '100dvh', display: 'flex', flexDirection: 'column' }}>
      <PCBInteractiveEditor />
    </div>
  )
}
