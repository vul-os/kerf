// PlasmaDischargeWrapper.jsx
//
// Thin wrapper for PlasmaDischargePanel.
// Accepts a JSON file content string, merges parsed keys over defaults,
// and renders the plasma discharge visualisation panel.
//
// Expected JSON fields (produced by plasma_discharge_simulate tool):
//   x_m                  : number[]   — spatial positions [m]
//   n_e_m3               : number[]   — electron density [m^-3]
//   n_i_m3               : number[]   — ion density [m^-3]
//   E_field_V_m          : number[]   — electric field [V/m]
//   phi_V                : number[]   — potential [V]
//   ionization_rate_m3_s : number[]   — Townsend source [m^-3 s^-1]
//   paschen_curve        : { pd_Pa_m: number[], V_bd_V: number[] }
//   current_density_A_m2 : number
//   sheath_thickness_m   : number
//   breakdown_estimate_V : number
//   converged            : boolean
//   gas                  : string
//   pressure_Pa          : number
//   gap_m                : number
//   voltage_V            : number
//   model_notes          : string     — honest model limitations

import Panel, { type PaschenCurve } from '../../../components/PlasmaDischargePanel.jsx'

export interface Props {
  content?: string
}

// PaschenCurve comes from the panel now that it is migrated — a local copy diverged
// (pd_Pa_m optional here, required there) and made the props un-assignable.
interface PlasmaDischargeContent {
  x_m: number[] | null
  n_e_m3: number[] | null
  n_i_m3: number[] | null
  E_field_V_m: number[] | null
  phi_V: number[] | null
  ionization_rate_m3_s: number[] | null
  paschen_curve: PaschenCurve | null
  current_density_A_m2: number | null
  sheath_thickness_m: number | null
  breakdown_estimate_V: number | null
  converged: boolean
  gas: string
  pressure_Pa: number | null
  gap_m: number | null
  voltage_V: number | null
  model_notes: string | null
}

const DEFAULTS: PlasmaDischargeContent = {
  x_m: null,
  n_e_m3: null,
  n_i_m3: null,
  E_field_V_m: null,
  phi_V: null,
  ionization_rate_m3_s: null,
  paschen_curve: null,
  current_density_A_m2: null,
  sheath_thickness_m: null,
  breakdown_estimate_V: null,
  converged: false,
  gas: 'air',
  pressure_Pa: null,
  gap_m: null,
  voltage_V: null,
  model_notes: null,
}

function parseContent(content: string | undefined): Partial<PlasmaDischargeContent> {
  if (!content || typeof content !== 'string') return {}
  try { return JSON.parse(content) || {} } catch { return {} }
}

export default function PlasmaDischargeWrapper({ content }: Props) {
  const props = { ...DEFAULTS, ...parseContent(content) }
  return <Panel {...props} />
}
