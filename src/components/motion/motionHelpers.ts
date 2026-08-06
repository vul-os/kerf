// motionHelpers.ts — pure helpers extracted from AssemblyMotionStudioPanel.tsx (T-509).
//
// Split into its own module because react-refresh/only-export-components (active for every
// .tsx file per eslint.config.js) flags a component file that also exports plain
// constants/functions — this predates the migration (verified against the pre-migration .jsx:
// same rule, same violation), so moving the pure helpers here is the fix rather than a
// suppression. Behavior is unchanged; only the module boundary moved.

import type { Joint, JointType, Driver, SimParams, StudySpec } from './motionTypes'

export const JOINT_TYPES: JointType[] = ['revolute', 'prismatic', 'cylindrical', 'fixed', 'spherical']
export const DRIVER_TYPES: Array<Driver['type']> = ['constant_velocity', 'sinusoidal', 'table']

/**
 * Parse a "t theta" table string into { times, thetas } arrays.
 * Lines with < 2 parsable numbers are silently skipped.
 */
export function parseTableDriver(raw?: string | null): { times: number[]; thetas: number[] } {
  const times: number[] = []
  const thetas: number[] = []
  for (const line of (raw || '').split('\n')) {
    const parts = line.trim().split(/\s+/)
    if (parts.length < 2) continue
    const t = parseFloat(parts[0])
    const theta = parseFloat(parts[1])
    if (isFinite(t) && isFinite(theta)) {
      times.push(t)
      thetas.push(theta)
    }
  }
  return { times, thetas }
}

/** One body entry in a `motion_frame_timeline` request payload. */
export interface TimelineBody {
  name: string
  mass: number
  inertia: number[][]
  position: [number, number, number]
  velocity: [number, number, number]
}

/** A force/torque/table-driver entry in a `motion_frame_timeline` request payload. */
export type TimelineForce = Record<string, unknown>

export interface TimelinePayload {
  tool: 'motion_frame_timeline'
  args: {
    bodies: TimelineBody[]
    forces: TimelineForce[]
    dt: number
    n_steps: number
    record_every: number
  }
}

/**
 * Build the `motion_frame_timeline` tool payload from panel state.
 */
export function buildTimelinePayload(joints: Joint[], driver: Driver, sim: SimParams): TimelinePayload {
  const n_steps = Math.max(1, Math.round(sim.duration / sim.dt))
  const record_every = Math.max(1, Math.round(n_steps / Math.min(n_steps, sim.maxFrames ?? 300)))

  const componentIds: string[] = []
  for (const j of joints) {
    if (j.componentA && !componentIds.includes(j.componentA)) componentIds.push(j.componentA)
    if (j.componentB && !componentIds.includes(j.componentB)) componentIds.push(j.componentB)
  }
  if (componentIds.length === 0) componentIds.push('body_0')

  const bodies: TimelineBody[] = componentIds.map((id, i) => ({
    name: id,
    mass: 1.0,
    inertia: [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    position: [i * 0.5, 0, 0],
    velocity: [0, 0, 0],
  }))

  const forces: TimelineForce[] = [{ type: 'gravity', g: 9.80665 }]
  const driverForce = _driverForce(driver)
  if (driverForce) forces.push(driverForce)

  return {
    tool: 'motion_frame_timeline',
    args: { bodies, forces, dt: sim.dt, n_steps, record_every },
  }
}

function _driverForce(driver: Driver | null | undefined): TimelineForce | null {
  if (!driver) return null
  switch (driver.type) {
    case 'constant_velocity':
      return {
        type: 'applied',
        body_idx: 0,
        force: [0, 0, 0],
        torque: [0, 0, driver.velocity ?? 1.0],
      }
    case 'sinusoidal':
      return {
        type: 'applied',
        body_idx: 0,
        force: [0, 0, 0],
        torque: [0, 0, driver.amplitude ?? 1.0],
      }
    case 'table': {
      const { times, thetas } = parseTableDriver(driver.table ?? '')
      if (times.length < 2) return null
      return {
        type: 'table_driver',
        body_idx: 0,
        table_times: times,
        table_thetas: thetas,
        inertia: driver.inertia ?? 1.0,
        damping: driver.damping ?? 0.0,
        axis: [0, 0, 1],
      }
    }
    default:
      return null
  }
}

/**
 * Parse a motion study spec (from .motion file content) into panel defaults.
 * Returns { joints, driver, sim } or null.
 */
export function parseStudySpec(content?: string | Record<string, unknown> | null): StudySpec | null {
  if (!content) return null
  try {
    // `doc`'s shape is whatever the persisted .motion file happens to contain — a boundary
    // this slice does not own; the field reads below apply the same defensive defaults the
    // original parser did.
    const doc: Record<string, unknown> = typeof content === 'string' ? JSON.parse(content) : content
    if (!doc || typeof doc !== 'object') return null
    return {
      joints: Array.isArray(doc.joints) ? (doc.joints as Joint[]) : [],
      driver: (doc.driver as Driver) ?? { type: 'constant_velocity', velocity: 1.0 },
      sim: {
        dt: (doc.dt as number) ?? 0.01,
        duration: (doc.duration as number) ?? 2.0,
        maxFrames: (doc.maxFrames as number) ?? 300,
      },
    }
  } catch {
    return null
  }
}
