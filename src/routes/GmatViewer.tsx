/**
 * GmatViewer.jsx — Route page for the GMAT 3D Trajectory Viewer.
 *
 * Route: /gmat-viewer
 *
 * Shows a full-page wrapper around GmatTrajectoryViewer with a top bar
 * that holds the Load Mission control and mission metadata.
 * POSTs to /api/llm-tools/aerospace_load_gmat_trajectory when the user
 * clicks "Load Mission".
 */

import { useCallback, useState } from 'react'
import GmatTrajectoryViewer from '../components/aerospace/GmatTrajectoryViewer.jsx'

export default function GmatViewer() {
  const [trajectory, setTrajectory] = useState(null)   // null → use built-in fixture
  const [events,     setEvents]     = useState(null)
  const [loading,    setLoading]    = useState(false)
  const [error,      setError]      = useState(null)
  const [missionMeta, setMissionMeta] = useState(null)

  const handleLoadMission = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const res = await fetch('/api/llm-tools/aerospace_load_gmat_trajectory', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({}),
      })
      if (!res.ok) {
        const text = await res.text()
        throw new Error(`Server error ${res.status}: ${text}`)
      }
      const data = await res.json()
      if (data.trajectory && Array.isArray(data.trajectory)) {
        setTrajectory(data.trajectory)
        setEvents(data.events || [])
        setMissionMeta(data.mission || null)
      } else {
        throw new Error('Response missing trajectory array')
      }
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }, [])

  return (
    <div style={{
      minHeight: '100vh',
      background: '#020810',
      color: '#cce4ff',
      fontFamily: 'ui-monospace, SFMono-Regular, monospace',
      display: 'flex',
      flexDirection: 'column',
    }}>
      {/* Top bar */}
      <div style={{
        padding: '12px 24px',
        borderBottom: '1px solid #1a2a4a',
        display: 'flex',
        alignItems: 'center',
        gap: 20,
        flexShrink: 0,
        background: '#04091a',
      }}>
        <div style={{ display: 'flex', flexDirection: 'column' }}>
          <span style={{ color: '#80c0ff', fontWeight: 700, fontSize: 15, letterSpacing: 1 }}>
            GMAT 3D TRAJECTORY VIEWER
          </span>
          <span style={{ color: '#2a4a6a', fontSize: 11 }}>
            General Mission Analysis Tool — ECI / J2000 frame
          </span>
        </div>

        {missionMeta && (
          <div style={{ fontSize: 12, color: '#60a0d0', marginLeft: 'auto' }}>
            <span style={{ color: '#405878' }}>Mission: </span>
            {missionMeta.name || 'Custom'}
            {missionMeta.epoch && (
              <span style={{ color: '#405878', marginLeft: 8 }}>
                Epoch: {missionMeta.epoch}
              </span>
            )}
          </div>
        )}

        {error && (
          <div style={{ marginLeft: 'auto', color: '#ff6060', fontSize: 12, maxWidth: 300 }}>
            {error}
          </div>
        )}

        {loading && (
          <div style={{ marginLeft: 'auto', color: '#40a0ff', fontSize: 12 }}>
            Loading...
          </div>
        )}
      </div>

      {/* Viewer */}
      <div style={{
        flexGrow: 1,
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'center',
        padding: 24,
        gap: 0,
      }}>
        <GmatTrajectoryViewer
          trajectory={trajectory || undefined}
          events={events || undefined}
          width={900}
          height={560}
          onLoadMission={handleLoadMission}
        />
      </div>

      {/* Footer note */}
      <div style={{
        padding: '8px 24px',
        borderTop: '1px solid #0a1428',
        color: '#203040',
        fontSize: 11,
        flexShrink: 0,
      }}>
        Default scene: Apollo TLI fixture (50 sample points). Click "Load Mission" to fetch a GMAT trajectory from the backend.
      </div>
    </div>
  )
}
