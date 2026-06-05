// FEAView.jsx — tabbed container for all FEA / FEM solve panels.
//
// Tabs: Linear Static | Modal | Buckling | Fatigue | Vibration | Advanced FEM
//
// "Advanced FEM" hosts FEMSolverPanel (20+ extra tools):
//   Nonlinear Static, NL Bar, Truss Plastic, Explicit Dynamics,
//   Thermal (steady/transient), Acoustics FEM/BEM, Electrostatics,
//   Magnetostatics, High-Freq EM, CFD Navier-Stokes, Potential Flow,
//   Plate/Shell MITC4, Probabilistic FEA (LHS/Monte-Carlo).
//
// Props:
//   file       — current workspace file { id, kind, name }
//   projectId  — UUID
//
// Each panel gets (projectId, fileId) and independently manages its own
// job lifecycle via feaApi.js → /api/projects/{pid}/files/{fid}/fem.

import { useState } from 'react'
import LinearStaticPanel from './LinearStaticPanel.jsx'
import ModalPanel        from './ModalPanel.jsx'
import BucklingPanel     from './BucklingPanel.jsx'
import FatiguePanel      from './FatiguePanel.jsx'
import VibrationPanel    from './VibrationPanel.jsx'
import FEMSolverPanel    from './FEMSolverPanel.jsx'
import SolidFEMPanel     from './SolidFEMPanel.jsx'

const TABS = [
  { id: 'linear_static',    label: 'Linear Static', color: '#22d3ee' },
  { id: 'modal',            label: 'Modal',          color: '#a78bfa' },
  { id: 'buckling',         label: 'Buckling',       color: '#fbbf24' },
  { id: 'fatigue',          label: 'Fatigue',        color: '#f472b6' },
  { id: 'vibration',        label: 'Vibration',      color: '#34d399' },
  { id: 'solid',            label: 'Solid FEM',      color: '#38bdf8' },
  { id: 'advanced',         label: 'Advanced FEM',   color: '#fb923c' },
]

export default function FEAView({ file, projectId }) {
  const [activeTab, setActiveTab] = useState('linear_static')
  const fileId = file?.id

  return (
    <div style={{ fontFamily: 'ui-monospace, SFMono-Regular, Menlo, monospace', fontSize: 13 }}>
      {/* Tab strip */}
      <div
        style={{
          display: 'flex',
          gap: 0,
          borderBottom: '1px solid #1f2937',
          background: '#0f172a',
          overflowX: 'auto',
        }}
        role="tablist"
        aria-label="FEA analysis panels"
      >
        {TABS.map(tab => {
          const active = activeTab === tab.id
          return (
            <button
              key={tab.id}
              role="tab"
              aria-selected={active}
              aria-controls={`fea-panel-${tab.id}`}
              id={`fea-tab-${tab.id}`}
              onClick={() => setActiveTab(tab.id)}
              style={{
                padding: '8px 14px',
                background: 'none',
                border: 'none',
                borderBottom: active ? `2px solid ${tab.color}` : '2px solid transparent',
                color: active ? tab.color : '#6b7280',
                cursor: 'pointer',
                fontSize: 11,
                fontWeight: active ? 700 : 400,
                letterSpacing: '0.05em',
                textTransform: 'uppercase',
                whiteSpace: 'nowrap',
                fontFamily: 'inherit',
                transition: 'color 0.15s',
              }}
            >
              {tab.label}
            </button>
          )
        })}
      </div>

      {/* Panel body */}
      <div style={{ padding: '12px 0 0 0' }}>
        {activeTab === 'linear_static' && (
          <div role="tabpanel" id="fea-panel-linear_static" aria-labelledby="fea-tab-linear_static">
            <LinearStaticPanel projectId={projectId} fileId={fileId} />
          </div>
        )}
        {activeTab === 'modal' && (
          <div role="tabpanel" id="fea-panel-modal" aria-labelledby="fea-tab-modal">
            <ModalPanel projectId={projectId} fileId={fileId} />
          </div>
        )}
        {activeTab === 'buckling' && (
          <div role="tabpanel" id="fea-panel-buckling" aria-labelledby="fea-tab-buckling">
            <BucklingPanel projectId={projectId} fileId={fileId} />
          </div>
        )}
        {activeTab === 'fatigue' && (
          <div role="tabpanel" id="fea-panel-fatigue" aria-labelledby="fea-tab-fatigue">
            <FatiguePanel projectId={projectId} fileId={fileId} />
          </div>
        )}
        {activeTab === 'vibration' && (
          <div role="tabpanel" id="fea-panel-vibration" aria-labelledby="fea-tab-vibration">
            <VibrationPanel projectId={projectId} fileId={fileId} />
          </div>
        )}
        {activeTab === 'solid' && (
          <div role="tabpanel" id="fea-panel-solid" aria-labelledby="fea-tab-solid">
            <SolidFEMPanel projectId={projectId} fileId={fileId} />
          </div>
        )}
        {activeTab === 'advanced' && (
          <div role="tabpanel" id="fea-panel-advanced" aria-labelledby="fea-tab-advanced">
            <FEMSolverPanel projectId={projectId} fileId={fileId} />
          </div>
        )}
      </div>
    </div>
  )
}
