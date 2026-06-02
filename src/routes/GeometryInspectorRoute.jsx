// GeometryInspectorRoute — wraps GeometryInspector for /tools/geometry-inspector.
// Passes projectId from the URL search param if present.

import { useSearchParams } from 'react-router-dom'
import GeometryInspector from '../components/brep/GeometryInspector.jsx'

export default function GeometryInspectorRoute() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? undefined
  return <GeometryInspector projectId={projectId} />
}
