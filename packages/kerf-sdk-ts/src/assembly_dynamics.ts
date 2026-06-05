/**
 * assembly_dynamics.ts
 * ====================
 * Frontend data types, result overlay renderer, and clash panel helpers
 * for assembly interference detection and assembly motion studies.
 *
 * Provides:
 *   - TypeScript interfaces matching kerf_cad_core.clash / kerf_motion
 *     JSON payloads (no coupling to a specific UI framework).
 *   - ClashPanelResult: parse + summarise a clash_detect response.
 *   - MotionStudyResult: parse + summarise an assembly_run_motion_study response.
 *   - renderClashOverlay(result): produce an SVG-compatible overlay descriptor
 *     (plain data, no DOM dependency).
 *   - renderMotionTimeline(result): produce a timeline descriptor for
 *     interference-over-time display.
 *
 * All functions are pure — no side effects, no DOM access.  Callers
 * integrate the returned descriptors into whatever renderer they use.
 */

// ---------------------------------------------------------------------------
// Clash detection types
// ---------------------------------------------------------------------------

export type ClashType = "hard" | "clearance" | "coincident";

export interface ClashRecord {
  a: string;
  b: string;
  discipline_a: string | null;
  discipline_b: string | null;
  discipline_pair: string;
  type: ClashType;
  depth: number;
}

export interface DisciplinePairSummary {
  hard: number;
  clearance: number;
  coincident: number;
  total: number;
}

export interface ClashDetectPayload {
  ok: boolean;
  clashes: ClashRecord[];
  clash_count: number;
  by_discipline_pair: Record<string, DisciplinePairSummary>;
  errors: string[];
}

// ---------------------------------------------------------------------------
// Motion study types
// ---------------------------------------------------------------------------

export interface BodyTrajectory {
  instance_id: string;
  t: number[];
  positions: [number, number, number][];
  velocities: [number, number, number][];
}

export interface InterferenceEvent {
  component_a: string;
  component_b: string;
  t_start: number;
  t_end: number;
  max_penetration_mm: number;
  penetration_point: [number, number, number];
}

export interface InterferenceReport {
  events: InterferenceEvent[];
  frames_swept: number;
  total_collision_frames: number;
  clearance_min_mm: number | null;
  bodies_at_min_clearance: [string, string] | null;
}

export interface MotionStudyPayload {
  ok: boolean;
  trajectories: BodyTrajectory[];
  interference: InterferenceReport;
  n_steps: number;
  dt: number;
  n_bodies: number;
  errors: string[];
}

// ---------------------------------------------------------------------------
// Clash panel result
// ---------------------------------------------------------------------------

/**
 * Parsed + summarised view of a clash_detect response, ready for display.
 */
export interface ClashPanelResult {
  /** All clashes from the payload. */
  clashes: ClashRecord[];
  /** Hard clashes only. */
  hardClashes: ClashRecord[];
  /** Clearance violations only. */
  clearanceClashes: ClashRecord[];
  /** Coincident / duplicate placements only. */
  coincidentClashes: ClashRecord[];
  /** Summary counts per discipline pair. */
  byDisciplinePair: Record<string, DisciplinePairSummary>;
  /** Total number of issues. */
  totalCount: number;
  /** True when any hard or coincident clash exists. */
  hasCritical: boolean;
  /** Non-fatal errors from the engine. */
  errors: string[];
}

/**
 * Parse a raw clash_detect JSON payload into a ClashPanelResult.
 *
 * @param raw  The parsed JSON object from the clash_detect tool response.
 */
export function parseClashPanel(raw: ClashDetectPayload): ClashPanelResult {
  const clashes = raw.clashes ?? [];
  const hardClashes = clashes.filter((c) => c.type === "hard");
  const clearanceClashes = clashes.filter((c) => c.type === "clearance");
  const coincidentClashes = clashes.filter((c) => c.type === "coincident");

  return {
    clashes,
    hardClashes,
    clearanceClashes,
    coincidentClashes,
    byDisciplinePair: raw.by_discipline_pair ?? {},
    totalCount: clashes.length,
    hasCritical: hardClashes.length > 0 || coincidentClashes.length > 0,
    errors: raw.errors ?? [],
  };
}

// ---------------------------------------------------------------------------
// Overlay descriptor for clash results
// ---------------------------------------------------------------------------

export type ClashSeverityColour = {
  hard: string;
  clearance: string;
  coincident: string;
};

const DEFAULT_COLOURS: ClashSeverityColour = {
  hard: "#ef4444",        // red-500
  clearance: "#f97316",   // orange-500
  coincident: "#a855f7",  // purple-500
};

export interface ClashOverlayItem {
  /** Instance ID of component A. */
  instanceA: string;
  /** Instance ID of component B. */
  instanceB: string;
  type: ClashType;
  depth: number;
  /** Suggested CSS / SVG fill colour for this severity. */
  colour: string;
  /** Short label for tooltip / accessibility. */
  label: string;
}

/**
 * Convert a ClashPanelResult into a list of overlay items suitable for
 * annotating a 3-D viewport or 2-D floor-plan.
 *
 * Returns one overlay item per clash record.  Callers position the items
 * based on component transform data from the assembly (not included here).
 */
export function renderClashOverlay(
  result: ClashPanelResult,
  colours: ClashSeverityColour = DEFAULT_COLOURS,
): ClashOverlayItem[] {
  return result.clashes.map((c) => ({
    instanceA: c.a,
    instanceB: c.b,
    type: c.type,
    depth: c.depth,
    colour: colours[c.type],
    label: buildClashLabel(c),
  }));
}

function buildClashLabel(c: ClashRecord): string {
  const depthStr = c.depth.toFixed(2);
  switch (c.type) {
    case "hard":
      return `Hard clash: ${c.a} ∩ ${c.b} (depth ${depthStr} mm)`;
    case "clearance":
      return `Clearance violation: ${c.a} — ${c.b} (gap ${depthStr} mm)`;
    case "coincident":
      return `Coincident: ${c.a} = ${c.b}`;
  }
}

// ---------------------------------------------------------------------------
// Motion timeline descriptor
// ---------------------------------------------------------------------------

export interface TimelineMarker {
  /** Time in seconds. */
  t: number;
  /** Pair key identifying the two bodies (sorted A < B). */
  pairKey: string;
  instanceA: string;
  instanceB: string;
  maxPenetrationMm: number;
  /** Duration of the event in seconds. */
  duration: number;
  /** Suggested colour for the timeline bar. */
  colour: string;
}

export interface MotionTimelineResult {
  /** Ordered list of interference event markers for timeline rendering. */
  markers: TimelineMarker[];
  /** Total simulated duration (seconds). */
  totalDuration: number;
  /** Minimum clearance gap observed across all non-colliding pairs. */
  clearanceMinMm: number | null;
  /** Pair with minimum clearance, or null if none. */
  bodiesAtMinClearance: [string, string] | null;
  /** Per-body max speed across the simulation. */
  bodyMaxSpeed: Record<string, number>;
  /** Non-fatal errors. */
  errors: string[];
}

/**
 * Build a MotionTimelineResult from an assembly_run_motion_study payload.
 *
 * The returned markers can be rendered as coloured intervals on a timeline
 * track (one track per interference pair).
 */
export function renderMotionTimeline(
  payload: MotionStudyPayload,
  interferenceColour = "#ef4444",
): MotionTimelineResult {
  const inf = payload.interference ?? {
    events: [],
    frames_swept: 0,
    total_collision_frames: 0,
    clearance_min_mm: null,
    bodies_at_min_clearance: null,
  };

  const totalDuration = payload.n_steps * payload.dt;

  const markers: TimelineMarker[] = inf.events.map((e) => {
    const a = e.component_a;
    const b = e.component_b;
    const pairKey = a <= b ? `${a}|${b}` : `${b}|${a}`;
    return {
      t: e.t_start,
      pairKey,
      instanceA: a,
      instanceB: b,
      maxPenetrationMm: e.max_penetration_mm,
      duration: Math.max(0, e.t_end - e.t_start),
      colour: interferenceColour,
    };
  });

  // Compute per-body max speed
  const bodyMaxSpeed: Record<string, number> = {};
  for (const traj of payload.trajectories ?? []) {
    let maxSpeed = 0;
    for (const vel of traj.velocities) {
      const speed = Math.sqrt(vel[0] ** 2 + vel[1] ** 2 + vel[2] ** 2);
      if (speed > maxSpeed) maxSpeed = speed;
    }
    bodyMaxSpeed[traj.instance_id] = maxSpeed;
  }

  return {
    markers,
    totalDuration,
    clearanceMinMm: inf.clearance_min_mm ?? null,
    bodiesAtMinClearance: inf.bodies_at_min_clearance ?? null,
    bodyMaxSpeed,
    errors: payload.errors ?? [],
  };
}

// ---------------------------------------------------------------------------
// Summary badge helpers (framework-agnostic text/class names)
// ---------------------------------------------------------------------------

export type SeverityBadge = {
  text: string;
  cssClass: string;
};

/**
 * Return a summary badge descriptor for a ClashPanelResult.
 * Text and class-name are human-readable; callers map cssClass to their
 * own colour system.
 */
export function clashSummaryBadge(result: ClashPanelResult): SeverityBadge {
  if (result.hardClashes.length > 0) {
    return {
      text: `${result.hardClashes.length} hard clash${result.hardClashes.length > 1 ? "es" : ""}`,
      cssClass: "badge-error",
    };
  }
  if (result.coincidentClashes.length > 0) {
    return {
      text: `${result.coincidentClashes.length} coincident`,
      cssClass: "badge-warning",
    };
  }
  if (result.clearanceClashes.length > 0) {
    return {
      text: `${result.clearanceClashes.length} clearance`,
      cssClass: "badge-info",
    };
  }
  return { text: "No clashes", cssClass: "badge-success" };
}
