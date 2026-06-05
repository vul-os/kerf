/**
 * Tests for assembly_dynamics.ts
 *
 * Coverage
 * --------
 * 1.  parseClashPanel: empty clashes → totalCount=0, hasCritical=false.
 * 2.  parseClashPanel: hard clash → hasCritical=true.
 * 3.  parseClashPanel: clearance only → hasCritical=false.
 * 4.  parseClashPanel: coincident → hasCritical=true.
 * 5.  parseClashPanel: mixed types → correct bucket counts.
 * 6.  parseClashPanel: byDisciplinePair passthrough.
 * 7.  parseClashPanel: errors passthrough.
 * 8.  renderClashOverlay: correct overlay count.
 * 9.  renderClashOverlay: hard clash uses hard colour.
 * 10. renderClashOverlay: label contains instance ids.
 * 11. renderClashOverlay: custom colours applied.
 * 12. renderClashOverlay: clearance label shows 'gap'.
 * 13. renderMotionTimeline: empty events → markers=[].
 * 14. renderMotionTimeline: totalDuration = n_steps × dt.
 * 15. renderMotionTimeline: single event → one marker.
 * 16. renderMotionTimeline: marker pairKey is alphabetically sorted.
 * 17. renderMotionTimeline: duration computed from t_start / t_end.
 * 18. renderMotionTimeline: bodyMaxSpeed computed correctly.
 * 19. renderMotionTimeline: clearanceMinMm and bodiesAtMinClearance.
 * 20. renderMotionTimeline: errors passthrough.
 * 21. clashSummaryBadge: no clashes → badge-success.
 * 22. clashSummaryBadge: hard clashes → badge-error.
 * 23. clashSummaryBadge: clearance only → badge-info.
 * 24. clashSummaryBadge: coincident only → badge-warning.
 * 25. buildClashLabel: coincident format.
 */

import { describe, it, expect } from "vitest";
import {
  parseClashPanel,
  renderClashOverlay,
  renderMotionTimeline,
  clashSummaryBadge,
  type ClashDetectPayload,
  type MotionStudyPayload,
} from "../src/assembly_dynamics.js";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makePayload(
  clashes: ClashDetectPayload["clashes"] = [],
  byDisciplinePair: ClashDetectPayload["by_discipline_pair"] = {},
  errors: string[] = [],
): ClashDetectPayload {
  return {
    ok: true,
    clashes,
    clash_count: clashes.length,
    by_discipline_pair: byDisciplinePair,
    errors,
  };
}

function makeClash(
  a: string,
  b: string,
  type: "hard" | "clearance" | "coincident",
  depth = 1.0,
) {
  return {
    a,
    b,
    discipline_a: null,
    discipline_b: null,
    discipline_pair: "unclassified vs unclassified",
    type,
    depth,
  };
}

function makeMotionPayload(
  events: MotionStudyPayload["interference"]["events"] = [],
  trajectories: MotionStudyPayload["trajectories"] = [],
  n_steps = 100,
  dt = 0.01,
): MotionStudyPayload {
  return {
    ok: true,
    trajectories,
    interference: {
      events,
      frames_swept: n_steps,
      total_collision_frames: events.length,
      clearance_min_mm: null,
      bodies_at_min_clearance: null,
    },
    n_steps,
    dt,
    n_bodies: trajectories.length,
    errors: [],
  };
}

function makeEvent(
  a: string,
  b: string,
  t_start: number,
  t_end: number,
  depth = 0.5,
) {
  return {
    component_a: a,
    component_b: b,
    t_start,
    t_end,
    max_penetration_mm: depth,
    penetration_point: [0, 0, 0] as [number, number, number],
  };
}

// ---------------------------------------------------------------------------
// 1. parseClashPanel: empty clashes
// ---------------------------------------------------------------------------

describe("parseClashPanel: empty", () => {
  it("returns zero counts and hasCritical=false for empty input", () => {
    const result = parseClashPanel(makePayload());
    expect(result.totalCount).toBe(0);
    expect(result.hasCritical).toBe(false);
    expect(result.hardClashes).toHaveLength(0);
    expect(result.clearanceClashes).toHaveLength(0);
    expect(result.coincidentClashes).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 2. parseClashPanel: hard clash
// ---------------------------------------------------------------------------

describe("parseClashPanel: hard", () => {
  it("sets hasCritical=true when hard clash exists", () => {
    const p = makePayload([makeClash("a", "b", "hard", 2.5)]);
    const r = parseClashPanel(p);
    expect(r.hasCritical).toBe(true);
    expect(r.hardClashes).toHaveLength(1);
    expect(r.hardClashes[0]!.depth).toBe(2.5);
  });
});

// ---------------------------------------------------------------------------
// 3. parseClashPanel: clearance only
// ---------------------------------------------------------------------------

describe("parseClashPanel: clearance only", () => {
  it("hasCritical=false for clearance-only clashes", () => {
    const p = makePayload([makeClash("x", "y", "clearance", 0.5)]);
    const r = parseClashPanel(p);
    expect(r.hasCritical).toBe(false);
    expect(r.clearanceClashes).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 4. parseClashPanel: coincident
// ---------------------------------------------------------------------------

describe("parseClashPanel: coincident", () => {
  it("sets hasCritical=true for coincident clash", () => {
    const p = makePayload([makeClash("p", "q", "coincident", 0.0)]);
    const r = parseClashPanel(p);
    expect(r.hasCritical).toBe(true);
    expect(r.coincidentClashes).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 5. parseClashPanel: mixed types
// ---------------------------------------------------------------------------

describe("parseClashPanel: mixed", () => {
  it("correctly distributes clashes into type buckets", () => {
    const p = makePayload([
      makeClash("a", "b", "hard"),
      makeClash("c", "d", "clearance"),
      makeClash("e", "f", "clearance"),
      makeClash("g", "h", "coincident"),
    ]);
    const r = parseClashPanel(p);
    expect(r.totalCount).toBe(4);
    expect(r.hardClashes).toHaveLength(1);
    expect(r.clearanceClashes).toHaveLength(2);
    expect(r.coincidentClashes).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 6. parseClashPanel: byDisciplinePair passthrough
// ---------------------------------------------------------------------------

describe("parseClashPanel: byDisciplinePair", () => {
  it("passes byDisciplinePair through unchanged", () => {
    const byPair = {
      "mep vs structural": { hard: 1, clearance: 0, coincident: 0, total: 1 },
    };
    const r = parseClashPanel(makePayload([], byPair));
    expect(r.byDisciplinePair).toEqual(byPair);
  });
});

// ---------------------------------------------------------------------------
// 7. parseClashPanel: errors passthrough
// ---------------------------------------------------------------------------

describe("parseClashPanel: errors", () => {
  it("passes errors through unchanged", () => {
    const r = parseClashPanel(makePayload([], {}, ["unit-box fallback used"]));
    expect(r.errors).toEqual(["unit-box fallback used"]);
  });
});

// ---------------------------------------------------------------------------
// 8. renderClashOverlay: correct overlay count
// ---------------------------------------------------------------------------

describe("renderClashOverlay: count", () => {
  it("returns one item per clash", () => {
    const p = parseClashPanel(makePayload([
      makeClash("a", "b", "hard"),
      makeClash("c", "d", "clearance"),
    ]));
    const overlay = renderClashOverlay(p);
    expect(overlay).toHaveLength(2);
  });
});

// ---------------------------------------------------------------------------
// 9. renderClashOverlay: hard clash uses hard colour
// ---------------------------------------------------------------------------

describe("renderClashOverlay: colours", () => {
  it("hard clash gets the hard colour", () => {
    const p = parseClashPanel(makePayload([makeClash("a", "b", "hard")]));
    const overlay = renderClashOverlay(p);
    expect(overlay[0]!.colour).toBe("#ef4444");
  });

  it("clearance clash gets the clearance colour", () => {
    const p = parseClashPanel(makePayload([makeClash("a", "b", "clearance")]));
    const overlay = renderClashOverlay(p);
    expect(overlay[0]!.colour).toBe("#f97316");
  });

  it("coincident clash gets the coincident colour", () => {
    const p = parseClashPanel(makePayload([makeClash("a", "b", "coincident")]));
    const overlay = renderClashOverlay(p);
    expect(overlay[0]!.colour).toBe("#a855f7");
  });
});

// ---------------------------------------------------------------------------
// 10. renderClashOverlay: label contains instance ids
// ---------------------------------------------------------------------------

describe("renderClashOverlay: label", () => {
  it("hard label contains both instance ids", () => {
    const p = parseClashPanel(makePayload([makeClash("column-1", "beam-3", "hard", 2.0)]));
    const overlay = renderClashOverlay(p);
    expect(overlay[0]!.label).toContain("column-1");
    expect(overlay[0]!.label).toContain("beam-3");
  });
});

// ---------------------------------------------------------------------------
// 11. renderClashOverlay: custom colours applied
// ---------------------------------------------------------------------------

describe("renderClashOverlay: custom colours", () => {
  it("applies custom colour overrides", () => {
    const customColours = { hard: "#000000", clearance: "#111111", coincident: "#222222" };
    const p = parseClashPanel(makePayload([makeClash("a", "b", "hard")]));
    const overlay = renderClashOverlay(p, customColours);
    expect(overlay[0]!.colour).toBe("#000000");
  });
});

// ---------------------------------------------------------------------------
// 12. renderClashOverlay: clearance label shows 'gap'
// ---------------------------------------------------------------------------

describe("renderClashOverlay: clearance label", () => {
  it("clearance label mentions gap", () => {
    const p = parseClashPanel(makePayload([makeClash("x", "y", "clearance", 3.5)]));
    const overlay = renderClashOverlay(p);
    expect(overlay[0]!.label.toLowerCase()).toContain("gap");
  });
});

// ---------------------------------------------------------------------------
// 13. renderMotionTimeline: empty events
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: empty", () => {
  it("returns empty markers for no interference events", () => {
    const result = renderMotionTimeline(makeMotionPayload());
    expect(result.markers).toHaveLength(0);
  });
});

// ---------------------------------------------------------------------------
// 14. renderMotionTimeline: totalDuration
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: totalDuration", () => {
  it("computes totalDuration = n_steps × dt", () => {
    const result = renderMotionTimeline(makeMotionPayload([], [], 50, 0.02));
    expect(result.totalDuration).toBeCloseTo(1.0, 9);
  });
});

// ---------------------------------------------------------------------------
// 15. renderMotionTimeline: single event → one marker
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: single event", () => {
  it("produces exactly one marker for a single interference event", () => {
    const p = makeMotionPayload([makeEvent("arm", "housing", 0.3, 0.7)]);
    const result = renderMotionTimeline(p);
    expect(result.markers).toHaveLength(1);
  });
});

// ---------------------------------------------------------------------------
// 16. renderMotionTimeline: pairKey is alphabetically sorted
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: pairKey sorting", () => {
  it("pairKey is sorted alphabetically (a <= b)", () => {
    const p = makeMotionPayload([makeEvent("z_body", "a_body", 0.0, 0.1)]);
    const result = renderMotionTimeline(p);
    const key = result.markers[0]!.pairKey;
    // "a_body" < "z_body" alphabetically
    expect(key).toBe("a_body|z_body");
  });
});

// ---------------------------------------------------------------------------
// 17. renderMotionTimeline: duration from t_start / t_end
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: duration", () => {
  it("duration = t_end - t_start", () => {
    const p = makeMotionPayload([makeEvent("a", "b", 0.2, 0.8)]);
    const result = renderMotionTimeline(p);
    expect(result.markers[0]!.duration).toBeCloseTo(0.6, 9);
  });

  it("zero-duration event has duration=0", () => {
    const p = makeMotionPayload([makeEvent("a", "b", 0.5, 0.5)]);
    const result = renderMotionTimeline(p);
    expect(result.markers[0]!.duration).toBeCloseTo(0, 9);
  });
});

// ---------------------------------------------------------------------------
// 18. renderMotionTimeline: bodyMaxSpeed
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: bodyMaxSpeed", () => {
  it("computes max speed for each body", () => {
    const traj = [{
      instance_id: "body-a",
      t: [0, 0.1, 0.2],
      positions: [[0, 0, 0], [0.1, 0, 0], [0.2, 0, 0]] as [number, number, number][],
      velocities: [
        [1.0, 0, 0],
        [3.0, 0, 0],  // max speed = 3 m/s
        [2.0, 0, 0],
      ] as [number, number, number][],
    }];
    const p = makeMotionPayload([], traj);
    const result = renderMotionTimeline(p);
    expect(result.bodyMaxSpeed["body-a"]).toBeCloseTo(3.0, 9);
  });

  it("zero velocity body has maxSpeed=0", () => {
    const traj = [{
      instance_id: "still",
      t: [0, 1],
      positions: [[0, 0, 0], [0, 0, 0]] as [number, number, number][],
      velocities: [[0, 0, 0], [0, 0, 0]] as [number, number, number][],
    }];
    const p = makeMotionPayload([], traj);
    const result = renderMotionTimeline(p);
    expect(result.bodyMaxSpeed["still"]).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// 19. renderMotionTimeline: clearance + bodiesAtMinClearance
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: clearance", () => {
  it("passes through clearanceMinMm and bodiesAtMinClearance", () => {
    const payload: MotionStudyPayload = {
      ok: true,
      trajectories: [],
      interference: {
        events: [],
        frames_swept: 10,
        total_collision_frames: 0,
        clearance_min_mm: 2.5,
        bodies_at_min_clearance: ["body-a", "body-b"],
      },
      n_steps: 10,
      dt: 0.01,
      n_bodies: 2,
      errors: [],
    };
    const result = renderMotionTimeline(payload);
    expect(result.clearanceMinMm).toBe(2.5);
    expect(result.bodiesAtMinClearance).toEqual(["body-a", "body-b"]);
  });
});

// ---------------------------------------------------------------------------
// 20. renderMotionTimeline: errors passthrough
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: errors", () => {
  it("passes errors from payload", () => {
    const payload: MotionStudyPayload = {
      ok: true,
      trajectories: [],
      interference: {
        events: [],
        frames_swept: 5,
        total_collision_frames: 0,
        clearance_min_mm: null,
        bodies_at_min_clearance: null,
      },
      n_steps: 5,
      dt: 0.01,
      n_bodies: 0,
      errors: ["some non-fatal warning"],
    };
    const result = renderMotionTimeline(payload);
    expect(result.errors).toContain("some non-fatal warning");
  });
});

// ---------------------------------------------------------------------------
// 21. clashSummaryBadge: no clashes
// ---------------------------------------------------------------------------

describe("clashSummaryBadge", () => {
  it("returns badge-success when no clashes", () => {
    const p = parseClashPanel(makePayload());
    const badge = clashSummaryBadge(p);
    expect(badge.cssClass).toBe("badge-success");
    expect(badge.text).toContain("No");
  });

  it("returns badge-error when hard clashes exist", () => {
    const p = parseClashPanel(makePayload([makeClash("a", "b", "hard")]));
    const badge = clashSummaryBadge(p);
    expect(badge.cssClass).toBe("badge-error");
    expect(badge.text).toContain("hard");
  });

  it("returns badge-info for clearance only", () => {
    const p = parseClashPanel(makePayload([makeClash("a", "b", "clearance")]));
    const badge = clashSummaryBadge(p);
    expect(badge.cssClass).toBe("badge-info");
  });

  it("returns badge-warning for coincident only", () => {
    const p = parseClashPanel(makePayload([makeClash("a", "b", "coincident")]));
    const badge = clashSummaryBadge(p);
    expect(badge.cssClass).toBe("badge-warning");
  });

  it("hard takes precedence over coincident", () => {
    const p = parseClashPanel(makePayload([
      makeClash("a", "b", "hard"),
      makeClash("c", "d", "coincident"),
    ]));
    const badge = clashSummaryBadge(p);
    expect(badge.cssClass).toBe("badge-error");
  });
});

// ---------------------------------------------------------------------------
// 25. Multiple events produce correct marker count
// ---------------------------------------------------------------------------

describe("renderMotionTimeline: multiple events", () => {
  it("produces one marker per event", () => {
    const events = [
      makeEvent("a", "b", 0.1, 0.3),
      makeEvent("c", "d", 0.5, 0.7),
      makeEvent("a", "c", 0.8, 0.9),
    ];
    const p = makeMotionPayload(events);
    const result = renderMotionTimeline(p);
    expect(result.markers).toHaveLength(3);
  });
});
