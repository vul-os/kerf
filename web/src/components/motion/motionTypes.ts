// motionTypes.ts — shared types for src/components/motion/ (T-509).
//
// Local to this folder (not src/types/) — these describe the assembly motion-study domain
// model (joints/drivers/sim params) and the `motion_frame_timeline` / `fea_export_load_cases`
// backend tool result shapes, a boundary this slice does not own. Mined field-by-field from
// actual reads at each call site (femTypes.ts convention).

export type JointType = 'revolute' | 'prismatic' | 'cylindrical' | 'fixed' | 'spherical'

export interface Joint {
  type: JointType
  componentA?: string
  componentB?: string
  axis?: [number, number, number]
}

/** Motor/driver applied to joint 0 — discriminated by `type`. */
export type Driver =
  | { type: 'constant_velocity'; velocity?: number }
  | { type: 'sinusoidal'; amplitude?: number; frequency?: number }
  | { type: 'table'; table?: string; inertia?: number; damping?: number }

export interface SimParams {
  dt: number
  duration: number
  maxFrames?: number
}

/** Parsed `.motion` study spec (parseStudySpec's return shape). */
export interface StudySpec {
  joints: Joint[]
  driver: Driver
  sim: SimParams
}

/** One body's pose within a `motion_frame_timeline` frame. */
export interface BodyPose {
  body_name: string
  position: [number, number, number]
  velocity?: [number, number, number]
  /** [qw, qx, qy, qz] — see useMotionViewport's applyPoses destructure. */
  orientation_quat?: [number, number, number, number]
  orientation_euler?: [number, number, number]
}

export interface MotionFrame {
  t: number
  poses: BodyPose[]
}

export interface InterferenceEvent {
  body_a?: string
  body_b?: string
  t_start?: number
  t_end?: number
  max_penetration_mm?: number
}

/** `motion_frame_timeline` tool result (the `data.result ?? data` inner payload). */
export interface FrameTimeline {
  frame_count?: number
  frames: MotionFrame[]
  t?: number[]
  body_names?: string[]
  interference_events?: InterferenceEvent[]
  [field: string]: unknown
}
