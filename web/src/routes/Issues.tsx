/**
 * Issues.jsx — /issues route: BCF 3.0 issue-manager page.
 *
 * Thin route wrapper around <BCFIssueManager/>.
 * Lazy-loaded from App.jsx.
 */

import { useParams, useNavigate } from 'react-router-dom'
import { ArrowLeft, GitBranchPlus } from 'lucide-react'
import { LogoWordmark } from '../components/Logo.jsx'
import BCFIssueManager from '../components/bim/BCFIssueManager.jsx'

export default function Issues() {
  const { projectId } = useParams()
  const navigate      = useNavigate()

  return (
    <div className="h-screen flex flex-col bg-ink-950 text-ink-100 overflow-hidden">
      <header className="flex items-center gap-3 h-12 px-3 border-b border-ink-800 bg-ink-900 flex-shrink-0">
        {projectId && (
          <button
            type="button"
            onClick={() => navigate(`/projects/${projectId}`)}
            className="p-1.5 rounded hover:bg-ink-800 text-ink-300 hover:text-kerf-300"
            title="Back to editor"
          >
            <ArrowLeft size={15} />
          </button>
        )}
        <LogoWordmark />
        <span className="text-ink-700">/</span>
        <div className="flex items-center gap-1.5 text-sm text-ink-200">
          <GitBranchPlus size={13} className="text-kerf-300" />
          BCF Issues
        </div>
      </header>
      <main className="flex-1 min-h-0 overflow-hidden">
        <BCFIssueManager projectId={projectId} />
      </main>
    </div>
  )
}
