// RoomCfdWrapper.jsx
//
// Thin wrapper for RoomCfdPanel.
// Accepts a JSON file content string, merges parsed keys over defaults,
// and renders the 3-D room airflow CFD visualisation panel.
//
// Expected JSON fields (produced by cfd_room_airflow_3d LLM tool):
//   grid_dims                  : number[3]   [nX, nY, nZ]
//   grid_spacing_m             : number[3]   [dx, dy, dz]
//   room_dims_m                : number[3]   [Lx, Ly, Lz]
//   plan_velocity_mag          : number[][]  XY plan-view speed [m/s]
//   plan_temperature_C         : number[][]  XY plan-view temperature [°C]
//   plan_age_of_air_min        : number[][]  XY plan-view age-of-air [min]
//   section_velocity_w         : number[][]  XZ section vertical velocity [m/s]
//   section_temperature_C      : number[][]  XZ section temperature [°C]
//   T_mean_C                   : number
//   T_max_C                    : number
//   T_min_C                    : number
//   velocity_max_m_s           : number
//   velocity_mean_m_s          : number
//   mass_continuity_residual   : number
//   ventilation_effectiveness  : number
//   max_vertical_dT_K_m        : number
//   occupant_comfort           : object[]    per-occupant comfort dicts
//   model_notes                : string

import Panel from '../../../components/RoomCfdPanel.jsx'

const DEFAULTS = {
  grid_dims: null,
  grid_spacing_m: null,
  room_dims_m: null,
  plan_velocity_mag: null,
  plan_temperature_C: null,
  plan_age_of_air_min: null,
  section_velocity_w: null,
  section_temperature_C: null,
  T_mean_C: null,
  T_max_C: null,
  T_min_C: null,
  velocity_max_m_s: null,
  velocity_mean_m_s: null,
  mass_continuity_residual: null,
  ventilation_effectiveness: null,
  max_vertical_dT_K_m: null,
  occupant_comfort: [],
  model_notes: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function RoomCfdWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
