// ReactingFlowWrapper.jsx
// Wrapper for the multi-species reacting-flow panel.
// Accepts standard Editor props: { file, content, projectId, fileId }
// JSON-parses content and spreads over defaults before forwarding to panel.
import Panel from '../../../components/ReactingFlowPanel.jsx'

const DEFAULTS = {
  mechanism: null,
  n_species: null,
  species_names: [],
  outlet_mass_fractions: null,
  outlet_temperature_K: null,
  max_temperature_K: null,
  adiabatic_flame_temperature_K: null,
  fuel: null,
  outlet_fuel_conversion: null,
  mean_fuel_conversion: null,
  reactor_length_m: null,
  velocity_m_per_s: null,
  // Profiles (optional, present when return_profiles=true)
  x_m: null,
  temperature_K_profile: null,
  fuel_conversion_profile: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function ReactingFlowWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
