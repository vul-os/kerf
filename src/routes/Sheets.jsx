/**
 * /projects/:projectId/sheets — Sheet Manager full-page route.
 *
 * Wraps <SheetManagerPanel> with a standard project header.  Sheet state is
 * kept in local component state for now; a future iteration can persist via
 * the file API once a .drawing-list.json kind is defined.
 */

import { useNavigate, useParams } from 'react-router-dom'
import { ArrowLeft, LayoutList } from 'lucide-react'
import { LogoWordmark } from '../components/Logo.jsx'
import SheetManagerPanel from '../components/drawings/SheetManagerPanel.jsx'

export default function SheetsPage() {
  const { projectId } = useParams()
  const navigate = useNavigate()

  function handleBack() {
    navigate(projectId ? `/editor/${projectId}` : '/')
  }

  return (
    <div className="h-screen flex flex-col bg-ink-950 text-ink-100 overflow-hidden">

      {/* Top bar */}
      <header className="flex items-center gap-3 h-12 px-3 border-b border-ink-800 bg-ink-900 flex-shrink-0">
        <button
          type="button"
          onClick={handleBack}
          aria-label="Back to editor"
          className="p-1.5 rounded hover:bg-ink-800 text-ink-400 hover:text-ink-100 focus-visible:ring-2 focus-visible:ring-kerf-300 focus-visible:outline-none"
        >
          <ArrowLeft size={16} aria-hidden="true" />
        </button>

        <LogoWordmark className="h-5 w-auto shrink-0" />

        <div className="flex items-center gap-1.5 text-ink-400 text-sm">
          <LayoutList size={14} className="shrink-0" aria-hidden="true" />
          <span>Sheet Manager</span>
        </div>

        <div className="flex-1" />

        {projectId && (
          <span className="text-[11px] font-mono text-ink-500">
            {projectId.slice(0, 8)}
          </span>
        )}
      </header>

      {/* Main content */}
      <main className="flex-1 min-h-0 overflow-hidden p-4 md:p-6">
        <SheetManagerPanel />
      </main>
    </div>
  )
}
