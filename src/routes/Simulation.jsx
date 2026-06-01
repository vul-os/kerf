// Simulation.jsx — /simulation route: FEM / FEA solver panel standalone page.
//
// Wraps FEAView (5 core tabs) + FEMSolverPanel (20+ advanced tools tab).
// URL params:  ?projectId=<uuid>&fileId=<uuid>
//
// The page is reachable from the Header nav and from the /domains/femcfd
// domain page. Users can deep-link to a specific project+file to start
// a solver job directly.

import { useMemo } from 'react'
import Header from '../components/Header.jsx'
import FEAView from '../components/fea/FEAView.jsx'

export default function Simulation() {
  const { projectId, fileId } = useMemo(() => {
    if (typeof window === 'undefined') return {}
    const p = new URLSearchParams(window.location.search)
    return { projectId: p.get('projectId') || null, fileId: p.get('fileId') || null }
  }, [])

  return (
    <div style={{ minHeight: '100vh', background: '#0d1117' }}>
      <Header />
      <div style={{ maxWidth: 1100, margin: '0 auto', padding: '24px 16px' }}>
        <div style={{
          fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace',
          fontSize: 11,
          color: '#6b7280',
          marginBottom: 12,
          display: 'flex',
          alignItems: 'center',
          gap: 12,
        }}>
          <span style={{ fontSize: 16, fontWeight: 700, color: '#f3f4f6' }}>FEM / FEA Solver</span>
          {projectId && <span>project: {projectId.slice(0, 8)}…</span>}
          {fileId   && <span>file: {fileId.slice(0, 8)}…</span>}
          {!projectId && (
            <span style={{ color: '#f59e0b' }}>
              Pass ?projectId=&amp;fileId= to submit jobs. Demo mode: inputs visible, Run disabled.
            </span>
          )}
        </div>

        <FEAView
          file={fileId ? { id: fileId, kind: 'step', name: 'current file' } : null}
          projectId={projectId}
        />
      </div>
    </div>
  )
}
