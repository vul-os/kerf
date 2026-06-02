// ClashRoute — wraps AssemblyClashPanel for the /clash route.
// Passes projectId from the URL search param if present.

import { useSearchParams } from 'react-router-dom'
import AssemblyClashPanel from '../components/brep/AssemblyClashPanel.jsx'

export default function ClashRoute() {
  const [searchParams] = useSearchParams()
  const projectId = searchParams.get('project') ?? undefined
  return <AssemblyClashPanel projectId={projectId} />
}
