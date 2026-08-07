// GeometryInspect.jsx — /inspect route: B-rep Geometry Inspector standalone page.
//
// Wraps GeometryInspector with a Header + optional projectId from the URL query.
// Usage: /inspect  or  /inspect?projectId=<uuid>

import { useMemo } from 'react'
import Header from '../components/Header.jsx'
import GeometryInspector from '../components/brep/GeometryInspector.jsx'

export default function GeometryInspect() {
  const projectId = useMemo(() => {
    if (typeof window === 'undefined') return null
    const p = new URLSearchParams(window.location.search)
    return p.get('projectId') || null
  }, [])

  return (
    <div style={{ minHeight: '100vh', background: '#0d1117' }}>
      <Header />
      <div style={{ maxWidth: 1200, margin: '0 auto' }}>
        <GeometryInspector projectId={projectId} />
      </div>
    </div>
  )
}
