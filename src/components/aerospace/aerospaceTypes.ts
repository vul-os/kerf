// aerospaceTypes.ts — shared types for src/components/aerospace/ (T-509).
//
// Local to this folder (not src/types/) — these describe the ad-hoc JSON shapes of the
// backend's GMAT trajectory viewer, rocket-motor database, and orbit-determination
// (batch least-squares / EKF) LLM tool results, a boundary this slice does not own. Each
// interface is mined field-by-field from the `result.<field>` / `prop.<field>` reads at
// its call site (same convention as src/components/structural/structuralTypes.ts), with an
// `unknown` index signature where a given tool result carries fields no call site here reads.

// ---------------------------------------------------------------------------
// GmatTrajectoryViewer.tsx
// ---------------------------------------------------------------------------

/** One ECI state vector sample (km / km·s⁻¹) along a trajectory. */
export interface TrajectoryPoint {
  t: number
  x: number
  y: number
  z: number
  vx: number
  vy: number
  vz: number
  phase?: number
}

/** One mission event (burn, flyby, ...) keyed to a trajectory time. */
export interface MissionEvent {
  t: number
  label: string
  type: string
}

// ---------------------------------------------------------------------------
// MotorSelectPanel.tsx
// ---------------------------------------------------------------------------

/** One point of a solid-motor thrust curve. */
export interface ThrustPoint {
  time_s: number
  thrust_n: number
}

/** Rocket motor catalogue entry / detail record (Thrustcurve.org / RASP .eng shape). */
export interface Motor {
  name: string
  manufacturer?: string
  impulse_class?: string
  total_impulse_ns?: number
  average_thrust_n?: number
  peak_thrust_n?: number
  burn_time_s?: number
  isp_s?: number
  diameter_mm?: number
  length_mm?: number
  propellant_mass_g?: number
  total_mass_g?: number
  delays_s?: number[]
  n_thrust_points?: number
  thrust_curve?: ThrustPoint[]
  [field: string]: unknown
}

/** Filter criteria passed to `onFilter` (the `aero_motor_database` 'list' operation). */
export interface MotorFilter {
  impulse_class?: string
  manufacturer?: string
  diameter_mm?: number
}

// ---------------------------------------------------------------------------
// OrbitDeterminationPanel.tsx
// ---------------------------------------------------------------------------

/** Shared shape of `aero_orbit_determination` (batch LS) and `aero_ekf_orbit_determination`
 *  (EKF) results — the two estimators expose overlapping but not identical field names. */
export interface OrbitDeterminationResult {
  ok?: boolean
  converged?: boolean
  n_iter?: number
  /** Batch LS estimated state [rx,ry,rz,vx,vy,vz] (km, km/s). */
  x_estimated?: number[]
  /** EKF final state [rx,ry,rz,vx,vy,vz] (km, km/s). */
  state_final?: number[]
  rms_residual?: number
  rms_innovation?: number
  sigma_0?: number
  n_observations?: number
  covariance_trace?: number
  /** EKF per-component variance diagonal, same order as `state_final`. */
  covariance_diag?: number[]
  position_norm_km?: number
  /** Sampled state-history rows (used to build the EKF position-norm sparkline). */
  state_history_sample?: number[][]
  warnings?: string[]
  [field: string]: unknown
}
