/**
 * FamilyEditorRoute.jsx — Route wrapper for the GDL-replacement Family Editor.
 *
 * Accessible at /families.
 */

import { useNavigate } from 'react-router-dom'
import FamilyEditorPanel from '../components/bim/FamilyEditorPanel.jsx'

export default function FamilyEditorRoute() {
  const navigate = useNavigate()
  return (
    <div className="h-screen flex flex-col bg-ink-100 dark:bg-ink-950 p-4">
      <FamilyEditorPanel
        className="flex-1 max-w-5xl w-full mx-auto"
        onClose={() => navigate(-1)}
      />
    </div>
  )
}
