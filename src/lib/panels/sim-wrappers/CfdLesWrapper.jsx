// CfdLesWrapper.jsx
//
// Thin wrapper for CfdLesPanel.
// Accepts JSON content produced by cfd_les_simulate, cfd_des_simulate,
// or cfd_overset_rotating tool responses.
//
// All props are optional — the panel renders whichever sections have data.
//
// JSON fields by tool:
//
// cfd_les_simulate:
//   sgs_model, case, Re_lambda, n_steps, dt,
//   resolved_tke, modeled_tke, nu_sgs_mean,
//   tke_decay_ratio, u_rms, v_rms, w_rms,
//   wavenumbers, energy_spectrum,
//   unsteady, temporal_u_fluctuation, model_notes
//
// cfd_des_simulate:
//   variant, Re_tau, y_plus, model_index, blend,
//   n_rans_cells, n_les_cells, near_wall_rans, has_les_region,
//   resolved_tke, model_notes
//
// cfd_overset_rotating:
//   omega_rad_s, angle_deg, interpolation_error, conservation_error,
//   phi_sum_bg, phi_sum_sg, feature_rotated, interpolation_ok,
//   model_notes

import Panel from '../../../components/CfdLesPanel.jsx'

const DEFAULTS = {
  // LES
  sgs_model: null,
  case: null,
  Re_lambda: null,
  n_steps: null,
  dt: null,
  resolved_tke: null,
  modeled_tke: null,
  nu_sgs_mean: null,
  tke_decay_ratio: null,
  u_rms: null,
  v_rms: null,
  w_rms: null,
  wavenumbers: null,
  energy_spectrum: null,
  unsteady: null,
  temporal_u_fluctuation: null,
  // DES
  variant: null,
  Re_tau: null,
  y_plus: null,
  model_index: null,
  blend: null,
  n_rans_cells: null,
  n_les_cells: null,
  near_wall_rans: null,
  has_les_region: null,
  // Overset
  omega_rad_s: null,
  angle_deg: null,
  interpolation_error: null,
  conservation_error: null,
  phi_sum_bg: null,
  phi_sum_sg: null,
  feature_rotated: null,
  interpolation_ok: null,
  // Common
  ok: null,
  model_notes: null,
}

function parseContent(content) {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function CfdLesWrapper({ content }) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
