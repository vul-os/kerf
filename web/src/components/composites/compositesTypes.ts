// compositesTypes.ts — shared types for src/components/composites/ (T-509).
//
// Local to this folder (not src/types/) — these describe this folder's own ply/layup domain
// model and the ad-hoc JSON results of the backend's composites tool endpoints
// (`composites_clt`, `composites_failure_envelope`, `composites_drape`,
// `composites_afp_pathplan`), a boundary this slice does not own. Each result interface is
// mined field-by-field from the `result.<field>` reads at its call site (same convention as
// src/components/fea/femTypes.ts).

/** One ply in a laminate stack, as edited by LaminateStackup.tsx's ply table. */
export interface Ply {
  id?: string
  material?: string
  thickness: number
  angle: number
  E1?: number
  E2?: number
  G12?: number
  nu12?: number
  rho?: number
  costPerKg?: number
}

/**
 * A ply as consumed by LaminateFailureEnvelope.tsx — same elastic constants as {@link Ply}
 * plus the lamina strength allowables `composites_failure_envelope` requires.
 */
export interface FailurePly {
  angle: number
  E1: number
  E2: number
  G12: number
  nu12: number
  thickness: number
  Xt: number
  Xc: number
  Yt: number
  Yc: number
  S12: number
}

/** `composites_clt` result (classical laminate theory stiffness matrices). */
export interface CltResult {
  name?: string
  num_plies?: number
  total_thickness_mm?: number
  is_symmetric?: boolean
  A_matrix_N_per_mm?: number[][]
  B_matrix_N?: number[][]
  D_matrix_N_mm?: number[][]
  effective_moduli?: Record<string, number>
  [field: string]: unknown
}

/** One point on a biaxial first-ply-failure envelope. */
export interface EnvelopePoint {
  theta_deg: number
  Nx_fail_N_per_mm: number
  Ny_fail_N_per_mm: number
  lambda_crit?: number
}

/** `composites_failure_envelope` result. */
export interface EnvelopeResult {
  envelope_points?: EnvelopePoint[]
  max_uniaxial_Nx_N_per_mm?: number
  max_uniaxial_Ny_N_per_mm?: number
  num_plies?: number
  n_angles?: number
  [field: string]: unknown
}

/** `composites_drape` result (geodesic drape simulation over a surface). */
export interface DrapeResult {
  surface?: string
  nu?: number
  nv?: number
  shear_angle_deg?: {
    mean?: number
    max?: number
    min?: number
  }
  [field: string]: unknown
}

/** One rendered AFP tow course — `paths` are flat [x1,y1,x2,y2] segments (canvas space). */
export interface AfpCourse {
  paths: number[][]
  color?: string
  angle: number
}

/** `composites_afp_pathplan` result. */
export interface AfpResult {
  courses?: AfpCourse[]
  num_courses?: number
  [field: string]: unknown
}

/** One point of AFPToolpathView's cure-cycle profile (temperature vs. time). */
export interface CureCyclePoint {
  t: number
  temp: number
}

export interface CureCycleParams {
  courseWidth: number
  minRadius: number
  towCount: number
  angle: number
  rampRate: number
  dwellTemp: number
  dwellTime: number
  coolRate: number
}
