// EMFieldWrapper.jsx
// Thin wrapper for EMFieldPanel — parses JSON content from the file store
// and spreads parsed keys over safe defaults before forwarding to the panel.
import Panel from '../../../components/EMFieldPanel.jsx'
import type { Props as EMFieldPanelProps } from '../../../components/EMFieldPanel.jsx'

export interface Props {
  content?: string
}

// EMFieldPanel's declared prop types don't include `null`, but this wrapper's
// (pre-existing) defaults use null rather than leaving fields undefined; keep
// that behaviour and type the defaults loosely rather than widening the panel's
// own Props type.
const DEFAULTS: { [K in keyof EMFieldPanelProps]?: EMFieldPanelProps[K] | null } = {
  mode: 'electrostatics',
  ok: null,
  reason: null,
  phi: null,
  E_field: null,
  capacitance: null,
  energy: null,
  Az: null,
  B_field: null,
  inductance: null,
  force: null,
  nodes: null,
  elements: null,
}

function parseContent(content: string | undefined): Record<string, unknown> {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function EMFieldWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...(props as EMFieldPanelProps)} />
}
