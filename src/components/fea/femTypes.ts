// femTypes.ts — shared types for the FEA/FEM solve panels in this folder (T-509).
//
// These are NOT promoted to src/types/ because they describe the ad-hoc JSON body/result
// shapes of ~30 distinct backend FEM/CFD tools (fem_solid_static, fem_hyperelastic_solve,
// cfd_navier_stokes_steady, ...), reverse-engineered per-panel from `result.<field>` reads
// in FEMSolverPanel.jsx / SolidFEMPanel.jsx / HyperelasticSolverPanel.jsx / *Panel.jsx.
// The backend is a boundary this slice does not own and the field set is genuinely
// open-ended (new tools add new result fields over time), so `FemResult` below names every
// field observed at a call site with its real type and falls back to an index signature of
// `unknown` for anything not yet named — the same pattern src/types/geometry.ts uses for
// `JewelryFeatureNode`.
//
// job.status vocabulary: 'queued' | 'running' | 'done' | 'error' come from the backend poll
// endpoint; 'not_found' / 'unknown' are pollFemStatus's own client-side fallbacks (feaApi.ts).

/** Props shared by every panel/card in this folder — a FEM job always needs project+file scope. */
export interface FemPanelProps {
  projectId?: string
  fileId?: string
}

export interface FemJobContext {
  pid: string
  fid: string
  token: string | null
}

export interface FemSubmitResponse {
  job_id: string
  status: string
}

export type FemRunStatus = 'queued' | 'running' | 'done' | 'error' | 'not_found' | 'unknown'

/**
 * A single reaction-force entry (SolidFEMPanel's BeamStaticCard `result.reactions`) — either a
 * bare number or an object carrying it under `R`, per that card's `typeof v === 'object' ? v.R ?? v : v`.
 */
export type FemReactionValue = number | { R?: number }

/** One row of FatiguePanel's / VibrationPanel's mode table (fn/frequency + damping + DAF). */
export interface FemModeTableRow {
  mode?: number
  fn_hz?: number
  frequency_hz?: number
  zeta?: number
  DAF_at_resonance?: number
}

/** One step of HyperelasticSolverPanel's Newton-Raphson load path. */
export interface FemHyperelasticPathStep {
  lambda?: number
  stretch?: number
  reaction?: number
  P_fem?: number
  analytic?: number | null
}

/**
 * Union of every `result.<field>` shape read across the panels in this folder. Every named
 * field's type is the one actually consumed at its call site; unnamed fields fall back to
 * `unknown` via the index signature rather than widening the whole object to `any`.
 */
export interface FemResult {
  // Linear static / solid static
  max_vonmises_stress?: number
  max_vonmises_stress_pa?: number
  max_displacement?: number
  max_displacement_m?: number
  fos?: number
  factor_of_safety?: number
  stresses?: number[]
  element_vonmises_pa?: number[]
  node_displacements?: unknown[]

  // Modal
  frequencies?: number[]
  frequencies_hz?: number[]
  /** Per-mode array of per-node values; each node's value is a scalar or a multi-dof vector
   *  (ModalPanel.tsx's participation-factor reduce narrows with `Array.isArray(v)`). */
  mode_shapes?: Array<Array<number | number[]>>
  omega_rad_s?: number[]
  f_1_hz?: number
  first_natural_freq?: number
  flexural_rigidity_D?: number
  mode_table?: FemModeTableRow[]

  // Buckling
  buckling_load_factors?: number[]

  // Fatigue
  min_life_cycles?: number
  min_life?: number
  min_life_node?: string | number
  safety_factor?: number
  infinite_life?: boolean
  damage_map?: Record<string, number>
  life_map?: Record<string, number>
  multiaxial_flags?: Record<string, string>

  // Vibration / harmonic / random
  amplitude?: number[]
  amplitudes?: number[]
  freq_response?: { amplitude?: number[] }
  phase_deg?: number[]
  resonant_peak_hz?: number
  resonant_amplitude?: number
  rms_response?: number
  grms?: number
  miles_grms?: number
  sigma_3_response?: number
  sigma_3?: number

  // Beam / bar static
  max_deflection?: number
  max_deflection_m?: number
  thermal_stress_pa?: number
  reactions?: Record<string, FemReactionValue>
  deflection_profile?: number[]
  x_coords?: number[]

  // Nonlinear static / bar / truss / explicit dynamics
  converged?: boolean
  load_steps_completed?: number
  plastic_strain_max?: number
  max_stress?: number
  steps_converged?: number
  stress_history?: number[]
  strain_history?: number[]
  time_steps?: number
  kinetic_energy?: number
  strain_energy?: number
  plastic_elements?: number

  // Thermal
  max_temperature?: number
  min_temperature?: number
  max_heat_flux?: number
  convergence_residual?: number

  // Acoustics / EM
  cavity_modes?: number[]
  spl_dB?: number
  radiation_efficiency?: number
  max_electric_field?: number
  capacitance?: number
  energy?: number
  max_b_field?: number
  inductance?: number
  magnetic_energy?: number
  cutoff_frequencies?: number[]
  s_params?: Record<string, number | string>
  sparams?: Record<string, number | string>

  // CFD
  max_velocity?: number
  reynolds_number?: number
  pressure_drop?: number
  iterations?: number
  cp?: number[]
  stagnation_pressure?: number
  drag_coefficient?: number

  // Plate / shell
  max_moment_x?: number
  max_moment_y?: number

  // Probabilistic / uncertainty propagation
  mean_max_stress?: number
  std_max_stress?: number
  pf_yield?: number
  cov?: number
  samples_run?: number

  // Hyperelastic
  max_stretch?: number
  max_nominal_P?: number
  J_min?: number
  J_max?: number
  n_nodes?: number
  n_elements?: number
  nr_iters_last?: number
  steps_done?: number
  analytic_error_pct?: number
  deformed_nodes?: number
  path?: FemHyperelasticPathStep[]

  // Genuinely open-ended: new backend tools add result fields faster than this file can name
  // them. Boundary this slice does not own (backend `input_spec`/result JSON) — `unknown`,
  // never `any`, so a caller must narrow before use, same as the array/object fields above.
  [field: string]: unknown
}

export interface FemJobStatus {
  status: FemRunStatus
  job_id?: string
  result?: FemResult
  error?: string
}
