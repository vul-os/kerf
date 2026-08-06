// geometry.ts — shared geometry/CAD domain types (T-501).
//
// Every shape here is derived from how the code actually behaves, not from what a CAD kernel
// "should" look like. See docs/typescript-migration.md's "Shared types (T-501)" section for the
// file map and the convention for adding a new shared type. Sources mined (cite these when in
// doubt, or extending):
//   - src/lib/occtWorker.js   — feature-tree evaluation; `switch (node.op)` is the discriminant
//                                (NOT `node.type` — verified directly against the evaluate loop),
//                                ~65 `op` values total. Its header comment documents the
//                                postMessage protocol; see workers.ts for that half.
//   - src/lib/occtRunner.js   — main-thread `.feature` file container (parseFeature/serializeFeature)
//   - src/lib/occtBridge.js   — `breptToMesh()`'s return shape (the wire Mesh), `_extractFaceMeta`
//   - src/lib/faceNaming.js   — FaceDescriptor / ModifiedMap typedefs (verbatim JSDoc), the
//                                face-name-map shape returned by `buildFaceNamesFor*()`
//   - src/lib/sketchSolver.js — SketchJSON: entities, constraints, plane specs, solved cache
//   - src/lib/sketchEdit.js   — canonical entity-creation call sites (confirms exact field names,
//                                e.g. line uses `p1`/`p2` not `a`/`b`; the `construction` flag;
//                                arc's `sweep_ccw`; bezier/bspline reference point ids, not
//                                inline coordinates)
//   - src/lib/sketchGeom2.js  — cross-check for entity field reads (e.g. `e.control_points`,
//                                `e.controls` resolved via `points.get(id)`, confirming those
//                                fields hold point-entity ids, not `{x,y}` literals)
//   - src/lib/geom3.js, src/lib/jscadWorker.js — confirm this codebase's Geom3 usage matches
//                                @jscad/modeling's own shipped type (re-exported below, not
//                                redeclared)
//   - src/lib/assembly.js     — Assembly JSON (components/overrides/mates) — a sibling document
//                                format, included here because assembly.js is a named T-501
//                                source and every slice touching it needs the same shapes
//
// Nothing in this file performs Zod-style runtime validation — these are compile-time-only
// contracts. `.feature`/`.sketch`/`.assembly` files are still parsed defensively by their owning
// modules (parseFeature, parseSketch, parseAssembly), which tolerate malformed JSON; the types
// below describe the *normalized* in-memory shape those parsers produce, not raw disk bytes.

import type { geometries } from '@jscad/modeling'

// ---------------------------------------------------------------------------
// JSCAD geometry — re-exported, not redeclared. @jscad/modeling ships its own precise .d.ts
// (node_modules/@jscad/modeling/src/geometries/geom3/type.d.ts:
//   `{ polygons: Poly3[]; transforms: Mat4; color?: Color }`, where `Mat4` is a 16-tuple) — the
// authoritative shape for anything this codebase's JSCAD path actually constructs. geom3.js and
// jscadWorker.js only ever *read* a subset of these fields (`polygons[].vertices`, `color`), but
// the objects flowing through are genuine `@jscad/modeling` values, so aliasing the real type is
// more accurate than hand-rolling a narrower one.
// ---------------------------------------------------------------------------

export type Geom3 = geometries.geom3.Geom3
export type Geom2 = geometries.geom2.Geom2

/**
 * One part entry as produced by jscadWorker.js's `normalizeParts()` / `toPart()` and consumed by
 * jscadRunner.js callers. `color` here is a packed 0xRRGGBB integer (see jscadWorker.js's
 * `geomColorToInt`) — a different representation from `Geom3.color`, which is jscad's own 0..1
 * float RGB(A) tuple.
 */
export interface JscadPart {
  id: string
  geom: Geom3
  color?: number
}

// ---------------------------------------------------------------------------
// Small shared primitives
// ---------------------------------------------------------------------------

/** A 3-component vector / point, as used throughout the OCCT + Three.js boundary. */
export type Vec3 = [x: number, y: number, z: number]

/** A 2-component vector / point (sketch (u,v) space, 2D outlines). */
export type Vec2 = [x: number, y: number]

/**
 * Axis-aligned bounding box.
 *
 * Not literally named `BBox` anywhere in src/lib — `geom3.js` and `assembly.js` both operate on
 * `THREE.Box3` instances (a class with `.min`/`.max` Vector3 and `.union`/`.copy` methods), and
 * `assembly.js`'s `buildBBoxProxy` doesn't compute a real bbox at all (it estimates a proxy cube
 * from a transform's translation magnitude — no min/max pair exists there). This is the
 * plain-data JSON-serializable shape a `THREE.Box3` reduces to; it is the narrowest type that
 * covers every place a "bounding box" concept appears in 3D. See {@link BBox2} for the 2D
 * (u,v) counterpart used by face-outline / projection code.
 */
export interface BBox {
  min: Vec3
  max: Vec3
}

/** 2D counterpart of {@link BBox} (sketch/outline (u,v) space). */
export interface BBox2 {
  min: Vec2
  max: Vec2
}

// ---------------------------------------------------------------------------
// Mesh — the triangulated wire format that crosses the occtWorker postMessage boundary
// (src/lib/occtBridge.js `breptToMesh`, assembled in src/lib/occtWorker.js)
// ---------------------------------------------------------------------------

/** Per-face metadata attached to a triangulated {@link Mesh} (occtBridge.js `_extractFaceMeta`). */
export interface FaceMeta {
  id: number
  planar: boolean
  origin: Vec3
  normal: Vec3
  uDir: Vec3
  vDir: Vec3
  centroid: Vec3
}

/** One named edge polyline entry inside a mesh's `edgeMap` (occtBridge.js `_emptyMesh`). */
export interface EdgeMapEntry {
  id: number
  /** Flat xyz triples for this edge's polyline vertices. */
  vertices: Float32Array
}

/** The `edgeMap` attached to a {@link Mesh} — a count plus the per-edge polyline list. */
export interface EdgeMap {
  count: number
  edges: EdgeMapEntry[]
}

/**
 * Stable face **name** map: `faceIndex (as string key) -> generated name string`
 * (e.g. `"feat-1.top"`). Produced by `faceNaming.js`'s `buildFaceNamesFor*`/`nameOpOutput`
 * functions, which key their output object with `String(face.index)` — genuinely string-keyed
 * (the source always builds/iterates it via `String(...)`/`Object.entries()`), so `Record<string,
 * string>` matches actual usage more honestly than a numeric index signature would. Consumed in
 * the reverse direction too: `faceRef.js`'s `resolveFaceRef` searches this map's entries for a
 * matching name to resolve a `target_face_name` back to a face index.
 */
export type FaceNameMap = Record<string, string>

/**
 * The full triangulated mesh crossing the occtWorker -> main-thread boundary. Fields through
 * `edgeMap` are exactly `breptToMesh()`'s return shape (occtBridge.js); `id` and `faceNames` are
 * added by occtWorker.js when it pushes a mesh entry onto the `result` message. All typed-array
 * fields are transferred (not structured-cloned) via the postMessage transfer list.
 */
export interface Mesh {
  /** Assigned by evaluateTree — e.g. `body-${n}` or the originating feature node's id. */
  id: string
  /** Flat xyz vertex positions. */
  vertices: Float32Array
  /** Flat triangle indices (three per triangle). */
  indices: Uint32Array
  /** Flat per-vertex xyz normals, same length as `vertices`. */
  normals: Float32Array
  /** One numeric face id per triangle (indexes into `faceMeta`). */
  faceIds: Uint32Array
  faceMeta: FaceMeta[]
  /** Flat xyz coordinates, two triples (one segment) at a time. */
  edgeSegs: Float32Array
  /** One numeric edge id per segment in `edgeSegs`. */
  edgeIds: Uint32Array
  edgeMap: EdgeMap
  /** Attached at mesh-push time, not part of breptToMesh's own return value. */
  faceNames: FaceNameMap
}

// ---------------------------------------------------------------------------
// Face / edge descriptors — the inputs to stable face naming (src/lib/faceNaming.js)
// ---------------------------------------------------------------------------

/**
 * Verbatim from faceNaming.js's `@typedef {Object} FaceDescriptor`. `sharedEdgeIndices` is added
 * via an intersection type at several call sites (`FaceDescriptor & { sharedEdgeIndices?:
 * number[] }`) rather than in the typedef itself — folded in here as optional since every use is
 * optional anyway.
 */
export interface FaceDescriptor {
  /** 0-based position in the TopExp_Explorer walk. */
  index: number
  surfaceKind: 'plane' | 'cylinder' | 'cone' | 'sphere' | 'torus' | 'bspline' | 'unknown'
  /** Total outer-loop edge count. */
  edgeCount: number
  /** Sorted array of edge curve types. */
  edgeKinds: Array<'line' | 'circle' | 'ellipse' | 'bspline' | 'other'>
  /** Sorted array of vertex valence counts (how many edges meet each vertex). */
  vertexValences: number[]
  /** Approximate surface normal at the centroid. */
  normal: Vec3
  /** Id of the originating sketch entity, or null. */
  sketchEntityId: string | null
  /** True when classified as a cap face by the caller. */
  isCap: boolean
  /** True when isCap && face is on the +axis side. */
  isTop: boolean
  sharedEdgeIndices?: number[]
}

/**
 * Verbatim from faceNaming.js's `@typedef {Object} ModifiedMap` — tracks how faces on an input
 * shape map onto faces of an operation's output shape.
 */
export interface ModifiedMap {
  /** inputFaceIndex -> array of outputFaceIndices that are "modified" images of it. Empty
   *  array means the face was deleted. */
  modified: Record<number, number[]>
  /** Indices of output faces that are genuinely new (no input-face parent). */
  generated: number[]
  /** Set of input-face indices that no longer exist in the output. */
  deletedInputs: Set<number>
}

// ---------------------------------------------------------------------------
// Shared configuration shape (feature-file and sketch-file "variants")
// ---------------------------------------------------------------------------

/**
 * A saved parameter variant. Both `.feature` files (occtRunner.js
 * `normalizeFeatureConfiguration`) and `.sketch` files (sketchSolver.js
 * `normalizeSketchConfiguration`) use this identical shape.
 */
export interface Configuration {
  id: string
  label: string
  params: Record<string, number>
}

// ---------------------------------------------------------------------------
// SketchJSON (src/lib/sketchSolver.js, src/lib/sketchEdit.js, src/lib/sketchGeom2.js)
// ---------------------------------------------------------------------------

/** A world-space frame resolved for a face-anchored sketch plane (sketchSolver.js `planeFaceFrame`). */
export interface SketchFrame {
  origin: Vec3
  normal: Vec3
  uDir: Vec3
  vDir: Vec3
}

/** The base XY/XZ/YZ (or named) plane a sketch can live on. */
export interface SketchPlaneBase {
  type: 'base'
  name: string
}

/**
 * A sketch anchored to a face on another `.feature` file. The persisted JSON only carries the
 * face-id reference; `frame` is filled in by the consumer (FeatureView / occtWorker) at
 * evaluation time and is absent until then (sketchSolver.js "Face-anchored plane handling" block).
 */
export interface SketchPlaneFace {
  type: 'face'
  file_id: string
  feature_node_id: string
  face_id: number
  frame?: SketchFrame
}

export type SketchPlane = SketchPlaneBase | SketchPlaneFace

interface SketchEntityBase {
  id: string
  /** Construction geometry — reference-only, excluded from the solved profile walk. */
  construction?: boolean
}

export interface SketchPoint extends SketchEntityBase {
  type: 'point'
  x: number
  y: number
}

/** `p1`/`p2` are ids of `point` entities, not raw coordinates (sketchEdit.js `addLine`, sketchSolver.js `buildPlanegcsPrimitives`). */
export interface SketchLine extends SketchEntityBase {
  type: 'line'
  p1: string
  p2: string
}

/** `center` is a `point` entity id (sketchEdit.js `addCircle`). */
export interface SketchCircle extends SketchEntityBase {
  type: 'circle'
  center: string
  radius: number
}

/**
 * `center`/`start`/`end` are all `point` entity ids (sketchEdit.js `addArc`). Angle/radius are
 * NOT persisted on the entity — sketchSolver.js and sketchGeom2.js both derive them on the fly
 * from the referenced points (`Math.atan2`/`Math.hypot`), so they are intentionally absent here.
 */
export interface SketchArc extends SketchEntityBase {
  type: 'arc'
  center: string
  start: string
  end: string
  sweep_ccw?: boolean
}

/** `center` is a `point` entity id (sketchEdit.js `addEllipse`). */
export interface SketchEllipse extends SketchEntityBase {
  type: 'ellipse'
  center: string
  rx: number
  ry: number
  rotation: number
}

/** Cubic B-spline; `controls` is an array of `point` entity ids, resolved via lookup in sketchGeom2.js (`points.get(id)`), degree fixed to 3 (sketchEdit.js `addBSpline`). */
export interface SketchBSpline extends SketchEntityBase {
  type: 'bspline'
  degree: number
  controls: string[]
}

/** Polynomial Bezier curve; `control_points` is an array of `point` entity ids (sketchEdit.js `addBezier`, sketchGeom2.js comment "Bezier is represented as control_points (array of point ids)"). */
export interface SketchBezier extends SketchEntityBase {
  type: 'bezier'
  degree: number
  control_points: string[]
}

/**
 * A projection of a 3D edge/curve into the sketch as construction (dotted) reference
 * geometry — appended during T-503 (found in `sketchEdit.js` `addExternalCurve`, missing
 * from the original T-501 mining pass; also read by `SketchView.jsx`'s external-curve
 * render branch, which switches on `curveType` and reads `p1`/`p2` (line), `center`/`radius`
 * (circle), or `center`/`radius`/`startAngle`/`endAngle` (arc) — never all of them on one
 * entity, hence every geometry field below is optional and the discriminant is `curveType`,
 * not `type` (which is always `'external_curve'`)). `construction` is always `true` in
 * practice (`addExternalCurve` hardcodes it) but kept optional to match {@link
 * SketchEntityBase} rather than narrowing the inherited field.
 */
export interface SketchExternalCurve extends SketchEntityBase {
  type: 'external_curve'
  source_file_id: string
  source_edge_id: string
  curveType: 'line' | 'circle' | 'arc'
  /** Named-field 2D point, NOT the {@link Vec2} tuple — matches `SketchBackdrop3D`'s
   *  `curveData` payload and SketchView.jsx's `e.p1.x`/`e.p1.y` reads verbatim. */
  p1?: { x: number; y: number }
  p2?: { x: number; y: number }
  center?: { x: number; y: number }
  radius?: number
  startAngle?: number
  endAngle?: number
  sweepCCw?: boolean
}

export type SketchEntity =
  | SketchPoint
  | SketchLine
  | SketchCircle
  | SketchArc
  | SketchEllipse
  | SketchBSpline
  | SketchBezier
  | SketchExternalCurve

/**
 * A dimensional constraint value: either a literal number, or a string equation reference like
 * `"${d}"` resolved via the equations scope (sketchSolver.js `numericValue`).
 */
export type SketchDimValue = number | string

/**
 * Sketch constraints, discriminated by `type`. Field lists come directly from the Kerf ->
 * planegcs translate loop in sketchSolver.js (`buildPlanegcsPrimitives`'s constraint switch); the
 * `entity_a_id`/`entity_b_id`/`construction_line_id` naming on `symmetric_over_line` is
 * intentionally inconsistent with the shorter `a`/`b` used elsewhere — that mirrors the source
 * exactly, it is not a typo here.
 *
 * Every constraint variant is intersected with `{ id: string }` (added during T-503) — every
 * real constraint object carries one (minted by `sketchEdit.js`'s `addConstraint` via
 * `shortId('cn')`) and it's load-bearing: `deleteConstraint`/`setConstraintValue` both look
 * constraints up by `c.id`. Missing from the original T-501 mining pass because the per-variant
 * field lists were mined from `buildPlanegcsPrimitives`'s translate switch, which only ever reads
 * the constraint-specific fields and never `id` itself.
 */
export type SketchConstraint = { id: string } & (
  | { type: 'coincident'; a: string; b: string }
  | { type: 'horizontal'; line: string }
  | { type: 'vertical'; line: string }
  | { type: 'parallel'; a: string; b: string }
  | { type: 'perpendicular'; a: string; b: string }
  | { type: 'tangent'; a: string; b: string }
  | { type: 'equal_length'; a: string; b: string }
  | { type: 'equal_radius'; a: string; b: string }
  | { type: 'distance'; a: string; b: string; value: SketchDimValue }
  | { type: 'distance_x'; a: string; b: string; value: SketchDimValue }
  | { type: 'distance_y'; a: string; b: string; value: SketchDimValue }
  | { type: 'angle'; a: string; b: string; value: SketchDimValue }
  | { type: 'radius'; circle: string; value: SketchDimValue }
  | { type: 'diameter'; circle: string; value: SketchDimValue }
  | { type: 'point_on_line'; point: string; line: string }
  | { type: 'point_on_arc'; point: string; arc: string }
  | { type: 'point_on_circle'; point: string; circle: string }
  | { type: 'point_on_ellipse'; ellipse: string; point: string }
  | { type: 'midpoint'; point: string; line: string }
  | { type: 'fixed'; point: string; x?: number; y?: number }
  | { type: 'symmetric'; a: string; b: string; line?: string; through?: string }
  | { type: 'symmetric_over_line'; entity_a_id: string; entity_b_id: string; construction_line_id: string }
  | { type: 'block'; refs: string[] }
  | { type: 'arc_on_circle'; arc: string; circle: string }
  | { type: 'arc_on_arc'; arc: string; otherArc: string }
  | { type: 'intersection_point'; point: string; line1: string; line2: string }
  | { type: 'collinear'; p1: string; p2: string; p3: string }
  | { type: 'ellipse_semi_major'; ellipse: string; value: SketchDimValue }
  | { type: 'ellipse_semi_minor'; ellipse: string; value: SketchDimValue }
  | { type: 'ellipse_rotation'; ellipse: string; value: SketchDimValue }
  | { type: 'bezier_tangent'; p0: string; p1: string; p2: string }
  | { type: 'bezier_g1'; p0: string; p1: string; p2: string }
  | { type: 'bezier_g2'; p_minus2: string; p_minus1: string; p_junction: string; p_plus1: string; p_plus2: string }
)

/**
 * Per-entity solved coordinates, keyed by entity id (sketchSolver.js: `solved[p.id] = { x, y }`
 * for points, `{ radius }` for circles, `{ start_angle, end_angle, radius }` for arcs). Modeled
 * as one shape with every field optional rather than a discriminated union, since the cache is
 * looked up by entity id without its own `type` tag — the entity's own `type` (in `entities`)
 * disambiguates which fields are populated.
 */
export interface SketchSolvedEntry {
  x?: number
  y?: number
  radius?: number
  start_angle?: number
  end_angle?: number
}

/**
 * The normalized in-memory Sketch shape produced by `parseSketch()` (sketchSolver.js). `visible_3d`
 * is an array of referenced file ids — confirmed via `SketchView.jsx`'s
 * `(sketch.visible_3d || []).includes(f.id)` / toggle logic, where `f.id` is a project file id.
 */
export interface SketchJSON {
  version: number
  plane: SketchPlane
  entities: SketchEntity[]
  constraints: SketchConstraint[]
  /** Referenced (context) file ids shown as translucent 3D backdrop geometry — see SketchView.jsx. */
  visible_3d: string[]
  /** Solver-output cache, keyed by entity id. */
  solved: Record<string, SketchSolvedEntry>
  metadata: Record<string, unknown>
  default_config?: string
  configurations?: Configuration[]
}

// ---------------------------------------------------------------------------
// FeatureNode / FeatureFile — the .feature tree (src/lib/occtWorker.js, src/lib/occtRunner.js)
// ---------------------------------------------------------------------------

/** Direction convention shared by pad/boss-adjacent ops. */
export type PadDirection = 'up' | 'down' | 'symmetric'

interface FeatureNodeBase {
  id: string
}

export interface PadFeatureNode extends FeatureNodeBase {
  op: 'pad'
  sketch_path: string
  height: number
  direction?: PadDirection
}

export interface BossWithDraftFeatureNode extends FeatureNodeBase {
  op: 'boss_with_draft'
  sketch_path: string
  height: number
  direction?: PadDirection
  draft_angle_deg: number
  draft_direction?: 'outward' | 'inward'
}

export interface PocketFeatureNode extends FeatureNodeBase {
  op: 'pocket'
  sketch_path: string
  depth: number
}

export interface RevolveFeatureNode extends FeatureNodeBase {
  op: 'revolve'
  sketch_path: string
  angle_deg?: number
  axis?: 'x' | 'y' | 'z'
}

export interface FilletFeatureNode extends FeatureNodeBase {
  op: 'fillet'
  radius: number
  edge_filter?: string
  edge_ids?: number[]
}

export interface ChamferFeatureNode extends FeatureNodeBase {
  op: 'chamfer'
  distance: number
  edge_filter?: string
  edge_ids?: number[]
}

export interface ShellFeatureNode extends FeatureNodeBase {
  op: 'shell'
  thickness: number
  face_ids?: number[]
}

export interface HoleFeatureNode extends FeatureNodeBase {
  op: 'hole' | 'hole_pattern'
  diameter: number
  depth: number
  sketch_path: string
}

/**
 * An axis reference resolved by occtBridge.js's `resolveAxisRef`: the literal
 * 'x'/'y'/'z', or a numeric (or numeric-string) edge id whose direction is
 * sampled from that edge's endpoints. NOT a raw direction vector — verified
 * against `resolveAxisRef`'s implementation (string keyword branch, else
 * `Number(axisRef)` treated as an edge id).
 */
export type AxisRef = 'x' | 'y' | 'z' | number | string

export interface LinearPatternFeatureNode extends FeatureNodeBase {
  op: 'linear_pattern'
  count: number
  spacing: number
  direction: AxisRef
}

export interface PolarPatternFeatureNode extends FeatureNodeBase {
  op: 'polar_pattern'
  count: number
  total_angle_deg?: number
  axis: AxisRef
}

/**
 * A plane reference resolved by occtBridge.js's `resolvePlaneRef` (only call
 * site: `opMirrorPattern`): 'xy'/'xz'/'yz', or a numeric (or numeric-string)
 * planar face id.
 */
export type PlaneRef = 'xy' | 'xz' | 'yz' | number | string

export interface MirrorPatternFeatureNode extends FeatureNodeBase {
  op: 'mirror_pattern'
  plane: PlaneRef
}

export interface PushPullFeatureNode extends FeatureNodeBase {
  op: 'push_pull'
  distance: number
  face_id?: number
  face_name?: string
}

export interface CutFromSketchFeatureNode extends FeatureNodeBase {
  op: 'cut_from_sketch'
  sketch_path: string
  depth: number
  reverse?: boolean
  target_face_id?: number
  target_face_name?: string
}

export interface Sweep1FeatureNode extends FeatureNodeBase {
  op: 'sweep1'
  profile_sketch_path: string
  path_sketch_path: string
  mode?: 'auto' | 'frenet' | 'corrected_frenet'
  twist_deg?: number
  scale_end?: number
}

export interface Sweep2FeatureNode extends FeatureNodeBase {
  op: 'sweep2'
  profile_sketch_path: string
  rail1_sketch_path: string
  rail2_sketch_path: string
  twist_deg?: number
  scale_end?: number
}

/**
 * Per-edge variable-radius fillet. `radii` pairs are `{ at, radius }`, `at` normalized 0..1 along
 * the edge parameter range, sorted ascending (occtBridge.js `buildVariableRadiusLaw`).
 */
export interface VariableRadiusFilletFeatureNode extends FeatureNodeBase {
  op: 'variable_radius_fillet'
  edges: Array<{ edge_id: number; radii: Array<{ at: number; radius: number }> }>
}

export interface LoftFeatureNode extends FeatureNodeBase {
  op: 'loft'
  profile_sketch_paths: string[]
  guide_curve_paths?: string[]
  closed?: boolean
  ruled?: boolean
  symmetric?: boolean
  continuity?: string
}

export interface BooleanFeatureNode extends FeatureNodeBase {
  op: 'boolean'
  kind: 'cut' | 'fuse' | 'common'
  target_a_id: string
  target_b_id: string
}

export interface SurfaceBooleanFeatureNode extends FeatureNodeBase {
  op: 'surface_boolean'
  kind: 'cut' | 'fuse' | 'common'
  target_a_id: string
  target_b_id: string
  coarse_mode?: boolean
  fuzziness?: number
  fuzzy_value?: number
  tolerance?: number
}

export interface SectionFeatureNode extends FeatureNodeBase {
  op: 'section'
  plane: string
  target_solid_ref: string
}

export interface TrimByCurveFeatureNode extends FeatureNodeBase {
  op: 'trim_by_curve'
  target_feature_ref: string
  target_face_name?: string
  trim_curve_ref: string
  keep_side?: string
  tolerance?: number
}

export interface NetworkSurfaceFeatureNode extends FeatureNodeBase {
  op: 'network_srf'
  u_curves?: string[]
  u_sketch_paths?: string[]
  v_curves?: string[]
  v_sketch_paths?: string[]
  continuity?: string
}

export interface BlendSurfaceFeatureNode extends FeatureNodeBase {
  op: 'blend_srf'
  edge1_id: string
  edge2_id: string
  continuity?: string
}

export interface SurfaceCurvatureCombsFeatureNode extends FeatureNodeBase {
  op: 'surface_curvature_combs'
  target_feature_ref: string
  target_face_name?: string
  uv_density?: number
  scale_factor?: number
  show_combs?: boolean
}

export interface OcctG3AuditFeatureNode extends FeatureNodeBase {
  op: 'occt_g3_audit'
  target_feature_ref: string
  target_face_name?: string
  uv_samples?: number
}

export interface SheetMetalFlangeFeatureNode extends FeatureNodeBase {
  op: 'sheet_metal_flange'
  edge_ref: string
  flange_length: number
  bend_angle_deg: number
  bend_radius: number
  thickness: number
  base_width?: number
  base_depth?: number
}

export interface HarnessTubeSweepFeatureNode extends FeatureNodeBase {
  op: 'harness_tube_sweep'
  waypoints: Vec3[]
  bundle_diameter_mm: number
}

/**
 * The jewelry-domain long tail (~35 ops under occtWorker.js: `gemstone`, `gem_seat`,
 * `jewelry_prong_head`, `jewelry_bezel`, `ring_shank`, `chain_assembly`, `pendant`, `earrings`,
 * ... and more). Every one of them shares the `position`/`orientation_deg` placement convention
 * (confirmed at the op-handler level) but each carries 5-15 op-specific numeric/string fields
 * (gem dimensions, prong counts, style enums) that are too numerous and too fast-moving to name
 * individually in this shared-types barrier. Modeled as a bounded open record rather than `any`
 * — every known field type in this domain is `number | string | boolean | number[]`, never an
 * arbitrary nested object, so `unknown` would be needlessly pessimistic for consumers that just
 * want the placement fields, and `any` would defeat strict-mode checking entirely. New jewelry
 * ops append their `op` string to {@link JewelryFeatureOp} as they're given real interfaces.
 */
export type JewelryFeatureOp =
  | 'gemstone' | 'gem_seat' | 'jewelry_prong_head' | 'jewelry_bezel' | 'jewelry_channel'
  | 'jewelry_pave' | 'ring_shank' | 'channel_seat' | 'bezel_seat' | 'fishtail_seat'
  | 'multi_stone_seat' | 'chain_assembly' | 'pendant' | 'earrings' | 'brooch' | 'cufflink'
  | 'bangle' | 'decorative_apply' | 'pave_field_seat' | 'cluster_halo_seat' | 'gypsy_seat'
  | 'baguette_channel_seat' | 'jewelry_prong_variant' | 'jewelry_head_gallery'
  | 'jewelry_under_bezel' | 'jewelry_peg_setting' | 'jewelry_coronet'
  | 'jewelry_suspension_mount' | 'jewelry_vtip_protector' | 'jewelry_bombe_cluster'
  | 'jewelry_patterned_bezel' | 'jewelry_trellis_prong' | 'jewelry_bar_channel_graduated'

export interface JewelryFeatureNode extends FeatureNodeBase {
  op: JewelryFeatureOp
  position: Vec3
  orientation_deg: Vec3
  [param: string]: unknown
}

/**
 * `to_solid`'s options bag is genuinely ambiguous at static-analysis time — the handler passes
 * `opts` through to a surface-to-solid bridge call without a fixed field list. Narrowed to
 * `Record<string, unknown>` rather than `any`, per T-501's "any is not acceptable" rule.
 */
export interface ToSolidFeatureNode extends FeatureNodeBase {
  op: 'to_solid'
  opts?: Record<string, unknown>
}

export type FeatureNode =
  | PadFeatureNode
  | BossWithDraftFeatureNode
  | PocketFeatureNode
  | RevolveFeatureNode
  | FilletFeatureNode
  | ChamferFeatureNode
  | ShellFeatureNode
  | HoleFeatureNode
  | LinearPatternFeatureNode
  | PolarPatternFeatureNode
  | MirrorPatternFeatureNode
  | PushPullFeatureNode
  | CutFromSketchFeatureNode
  | Sweep1FeatureNode
  | Sweep2FeatureNode
  | VariableRadiusFilletFeatureNode
  | LoftFeatureNode
  | BooleanFeatureNode
  | SurfaceBooleanFeatureNode
  | SectionFeatureNode
  | TrimByCurveFeatureNode
  | NetworkSurfaceFeatureNode
  | BlendSurfaceFeatureNode
  | SurfaceCurvatureCombsFeatureNode
  | OcctG3AuditFeatureNode
  | SheetMetalFlangeFeatureNode
  | HarnessTubeSweepFeatureNode
  | JewelryFeatureNode
  | ToSolidFeatureNode

/**
 * The normalized in-memory shape of a `.feature` file, produced by `parseFeature()`
 * (occtRunner.js). Note the field is `features`, not `tree` — `tree` is only the name used for
 * the in-flight array once handed to the occt worker (see workers.ts `OcctEvaluateRequest`).
 */
export interface FeatureFile {
  version: number
  name: string
  features: FeatureNode[]
  metadata?: Record<string, unknown>
  default_config: string
  configurations: Configuration[]
}

/**
 * Map of sketch_path -> sketch content. occtRunner.js always sends sketches pre-stringified
 * (`JSON.stringify` in `applyEquations`), but occtWorker.js's own reader tolerates a pre-parsed
 * object defensively — modeled as the union of both to match actual tolerance at the boundary.
 */
export type SketchMap = Record<string, string | SketchJSON>

// ---------------------------------------------------------------------------
// Assembly JSON (src/lib/assembly.js) — a sibling document format, not a FeatureNode tree.
// Included here because assembly.js is a named T-501 mining source and every slice touching
// it (T-503 and later) needs the same shapes rather than re-deriving them.
// ---------------------------------------------------------------------------

/** Cross-project part reference (ROADMAP row 68), from `assembly.js`'s `parseExternalRef`. */
export interface AssemblyExternalRef {
  project_id: string
  file_id: string
  kind: 'board_3d' | 'board_outline_2d'
  pin: string
  /** ISO 8601 timestamp of the last time the editor fetched this cross-project source. */
  last_seen_updated_at?: string
}

/** One placed component in an assembly (assembly.js `parseAssembly`/`serializeAssembly`). */
export interface AssemblyComponent {
  id: string
  file_id: string
  /** Object/part id within the referenced file. `"*"` is the legacy wildcard sentinel. */
  object_id: string
  /** Row-major 4x4 transform matrix, 16 entries. */
  transform: number[]
  params?: Record<string, unknown>
  visible?: boolean
  /** RGB triple, each channel clamped to [0,1]. */
  color?: [number, number, number]
  config_id?: string
  external_ref?: AssemblyExternalRef
}

/** A BOM override row keyed by part file (assembly.js). */
export interface AssemblyBomOverride {
  part_file_id: string
  quantity_override?: number
  non_stocked?: boolean
  note?: string
}

/** One side of a mate (assembly.js `parseMateRef`). */
export interface AssemblyMateRef {
  component_id: string
  feature: 'face' | 'edge' | 'vertex' | 'axis'
  feature_id: string
  /** Persistent face/edge name, round-tripped alongside the legacy integer id (T6). */
  feature_name?: string
}

/** 3D assembly mate (ROADMAP row 49), from assembly.js `parseMate`. */
export interface AssemblyMate {
  id: string
  type: 'coincident' | 'concentric' | 'parallel' | 'perpendicular' | 'distance' | 'angle' | 'tangent'
  a: AssemblyMateRef
  b: AssemblyMateRef
  /** Non-null only for the dimensional mate types (`distance`, `angle`). */
  value: number | null
}

/** The normalized in-memory shape of a `.assembly` file. */
export interface AssemblyDocument {
  components: AssemblyComponent[]
  overrides?: AssemblyBomOverride[]
  mates?: AssemblyMate[]
}
