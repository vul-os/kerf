// FeatureView — editor for `.feature` files (OCCT B-rep timeline + Phase 3
// direct modeling on top).
//
// Layout:
//   * top      — single unified toolbar: Add-feature popover + file name +
//                feature timeline (chips) on the left; pick-mode controls
//                (Faces / Edges / Push-Pull / Sketch-on-face) on the right.
//   * center   — FeatureRenderer (Phase 3): clickable faces + edges, hover
//                highlight, push/pull drag, sketch-on-face, etc.
//   * right    — FeatureInspector for the selected feature. When the
//                inspector has selection-driven fields (Fillet/Chamfer
//                edges, Shell faces, pattern axes, ...) it shows the current
//                viewport selection and a "Pick in viewport" button that
//                arms a one-shot pick.
//   * bottom   — eval status, vertex/body count, viewport selection summary,
//                error banner, re-evaluate.
//
// Selection lifecycle:
//   - Selection is per-file, session-only (lives in the workspace store at
//     `featureSelection`). On file switch we clear it.
//   - Face/edge ids are NOT stable across structural feature edits — adding
//     or removing features re-runs the OCCT evaluator and edge ids shuffle
//     in TopExp explorer order. We display a yellow banner "Selections may
//     reset after structural changes" to set expectations. A future polish
//     would pin selections to (face_centroid, normal) tuples for soft-
//     persistence.
//
// Push/pull UX:
//   - Toolbar button "Push/Pull" toggles a special pick mode. When armed,
//     hovering a face highlights it amber. Mousedown anchors the drag,
//     mouse-move projects screen delta onto the face's normal direction
//     (SketchUp-style). Release commits — append a `push_pull` feature node
//     to the tree (positive distance → fuse outward, negative → cut inward).
//     The face's id is captured at click time; the worker re-evaluates on
//     commit and the topology re-numbers, so the inspector can't "edit" a
//     completed push/pull (it's stored as a generic node and the user has
//     to re-pick the face if they want to change the distance).
//
// Sketch-on-face UX:
//   - Toolbar button "Sketch on face" arms a one-shot face pick. Click a
//     face → modal asks for a sketch name + parent folder → creates a new
//     sketch file with `plane: {type:'face', file_id, feature_node_id,
//     face_id}`. The sketcher reads this and builds a world-space transform
//     from the OCCT face frame.

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Trash2, ChevronUp, ChevronDown, Box, Circle, RotateCcw,
  Disc, Layers, Drill, Sigma, AlertTriangle, Loader2, Play,
  Move, Crosshair, GitBranch, Repeat, FlipHorizontal,
  PencilLine, Pointer, Waves, Layers3, Aperture, Plus,
  X, ChevronRight, LayoutGrid, Combine, Scissors, Grid3x3,
  MoreHorizontal, SlidersHorizontal, Zap, Eye, Shield,
  Wrench, AlignLeft, Activity,
  Code, Settings, Cpu, FlaskConical, BarChart2, Filter,
  RefreshCw, ChevronLast, Droplets, Wind, Gauge,
  Spline, TrendingUp, Maximize2, Wand2, FlipVertical,
  GitMerge, SplitSquareHorizontal, Route, Ruler, ArrowUpDown,
  Workflow, Shuffle, Merge,
  Cuboid, Navigation, Share2, PackageOpen,
  BrainCircuit, Compass, Ungroup, Boxes,
  Pencil, PenLine, Eraser, ScanLine,
  Triangle, Hexagon, Minus, ChevronsUp,
  Scan, FileSearch, FileCog, FileOutput,
  Network, Component, LayoutDashboard, AlignCenter,
  ScanSearch, Sticker, FileText, LayoutTemplate,
} from 'lucide-react'
import FeatureRenderer from './FeatureRenderer.jsx'
import {
  runFeatures, prewarmOcct, newFeatureId,
  requestFaceOutline,
} from '../lib/occtRunner.js'
import { useWorkspace } from '../store/workspace.js'

// Catalog of feature operations the LLM tools also expose. Each entry
// describes the icon, default param values, and the schema for the right-
// hand parameter inspector.
const FEATURE_KINDS = [
  {
    op: 'pad',
    label: 'Pad',
    icon: Box,
    defaults: { sketch_path: '', height: 10, direction: 'up' },
    fields: [
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Sketch' },
      { key: 'height', kind: 'number', label: 'Height (mm)', min: 0.001 },
      { key: 'direction', kind: 'select', label: 'Direction', options: [
        { value: 'up', label: 'Up (+Z)' },
        { value: 'down', label: 'Down (-Z)' },
        { value: 'symmetric', label: 'Symmetric' },
      ] },
    ],
  },
  {
    op: 'boss_with_draft',
    label: 'Boss + draft',
    icon: Box,
    defaults: {
      sketch_path: '',
      height: 10,
      direction: 'up',
      draft_angle_deg: 3,
      draft_direction: 'outward',
    },
    fields: [
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Sketch' },
      { key: 'height', kind: 'number', label: 'Height (mm)', min: 0.001 },
      { key: 'direction', kind: 'select', label: 'Direction', options: [
        { value: 'up', label: 'Up (+Z)' },
        { value: 'down', label: 'Down (-Z)' },
        { value: 'symmetric', label: 'Symmetric' },
      ] },
      { key: 'draft_angle_deg', kind: 'number', label: 'Draft angle (°)', min: -30, max: 30 },
      { key: 'draft_direction', kind: 'select', label: 'Draft direction', options: [
        { value: 'outward', label: 'Outward (widen away from sketch)' },
        { value: 'inward', label: 'Inward (narrow toward sketch)' },
      ] },
    ],
  },
  {
    op: 'pocket',
    label: 'Pocket',
    icon: Disc,
    defaults: { sketch_path: '', depth: 5, target_id: '' },
    fields: [
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Sketch' },
      { key: 'depth', kind: 'number', label: 'Depth (mm)', min: 0.001 },
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
    ],
  },
  {
    op: 'cut_from_sketch',
    label: 'Cut from sketch',
    icon: Disc,
    defaults: { target_id: '', target_face_id: -1, target_face_name: '', sketch_path: '', depth: 5, reverse: false },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'target_face_id', kind: 'face_picker_single', label: 'Face' },
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Sketch' },
      { key: 'depth', kind: 'number', label: 'Depth (mm)', min: 0.001 },
      { key: 'reverse', kind: 'bool', label: 'Reverse direction' },
    ],
  },
  {
    op: 'revolve',
    label: 'Revolve',
    icon: RotateCcw,
    defaults: { sketch_path: '', axis: 'z', angle_deg: 360 },
    fields: [
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Sketch' },
      { key: 'axis', kind: 'select', label: 'Axis', options: [
        { value: 'x', label: 'X' },
        { value: 'y', label: 'Y' },
        { value: 'z', label: 'Z' },
      ] },
      { key: 'angle_deg', kind: 'number', label: 'Angle (deg)', min: 1, max: 360 },
    ],
  },
  {
    op: 'fillet',
    label: 'Fillet',
    icon: Circle,
    defaults: { target_id: '', edge_filter: 'all', radius: 1, edge_ids: [] },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'edge_filter', kind: 'select', label: 'Edges', options: [
        { value: 'all', label: 'All' },
        { value: 'horizontal', label: 'Horizontal' },
        { value: 'vertical', label: 'Vertical' },
        { value: 'manual', label: 'Manual (pick)' },
      ] },
      { key: 'edge_ids', kind: 'edge_picker', label: 'Picked edges',
        showWhen: (n) => n.edge_filter === 'manual' },
      { key: 'radius', kind: 'number', label: 'Radius (mm)', min: 0.001 },
    ],
  },
  {
    op: 'chamfer',
    label: 'Chamfer',
    icon: Sigma,
    defaults: { target_id: '', edge_filter: 'all', distance: 1, edge_ids: [] },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'edge_filter', kind: 'select', label: 'Edges', options: [
        { value: 'all', label: 'All' },
        { value: 'horizontal', label: 'Horizontal' },
        { value: 'vertical', label: 'Vertical' },
        { value: 'manual', label: 'Manual (pick)' },
      ] },
      { key: 'edge_ids', kind: 'edge_picker', label: 'Picked edges',
        showWhen: (n) => n.edge_filter === 'manual' },
      { key: 'distance', kind: 'number', label: 'Distance (mm)', min: 0.001 },
    ],
  },
  {
    op: 'shell',
    label: 'Shell',
    icon: Layers,
    defaults: { target_id: '', thickness: 1, face_ids: [] },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'face_ids', kind: 'face_picker', label: 'Faces to remove' },
      { key: 'thickness', kind: 'number', label: 'Thickness (mm)', min: 0.001 },
    ],
  },
  {
    op: 'hole',
    label: 'Hole',
    icon: Drill,
    defaults: { sketch_path: '', target_id: '', diameter: 3, depth: 5 },
    fields: [
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Center sketch' },
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'diameter', kind: 'number', label: 'Diameter (mm)', min: 0.001 },
      { key: 'depth', kind: 'number', label: 'Depth (mm)', min: 0.001 },
    ],
  },
  {
    op: 'hole_pattern',
    label: 'Hole pattern',
    icon: LayoutGrid,
    defaults: { target_id: '', sketch_path: '', diameter: 3, depth: 5 },
    fields: [
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Points sketch' },
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'diameter', kind: 'number', label: 'Diameter (mm)', min: 0.001 },
      { key: 'depth', kind: 'number', label: 'Depth (mm)', min: 0.001 },
    ],
  },
  {
    op: 'linear_pattern',
    label: 'Linear pat.',
    icon: Repeat,
    defaults: { direction: 'x', count: 3, spacing: 10 },
    fields: [
      { key: 'direction', kind: 'axis_picker', label: 'Direction (axis or edge)' },
      { key: 'count', kind: 'number', label: 'Count', min: 2, step: 1 },
      { key: 'spacing', kind: 'number', label: 'Spacing (mm)' },
    ],
  },
  {
    op: 'polar_pattern',
    label: 'Polar pat.',
    icon: GitBranch,
    defaults: { axis: 'z', count: 6, total_angle_deg: 360 },
    fields: [
      { key: 'axis', kind: 'axis_picker', label: 'Axis (axis or edge)' },
      { key: 'count', kind: 'number', label: 'Count', min: 2, step: 1 },
      { key: 'total_angle_deg', kind: 'number', label: 'Total angle (deg)', min: 1, max: 360 },
    ],
  },
  {
    op: 'mirror_pattern',
    label: 'Mirror',
    icon: FlipHorizontal,
    // T6: plane_face_name dual-writes the persistent face name alongside the
    // plane field (which can be a numeric face id when picked from the viewport).
    defaults: { plane: 'xy', plane_face_name: '' },
    fields: [
      { key: 'plane', kind: 'plane_picker', label: 'Plane (axis-pair or face)' },
    ],
  },
  {
    op: 'push_pull',
    label: 'Push/Pull',
    icon: Move,
    defaults: { face_id: -1, face_name: '', distance: 0 },
    fields: [
      { key: 'face_id', kind: 'face_picker_single', label: 'Face' },
      { key: 'distance', kind: 'number', label: 'Distance (mm) — negative = into body' },
    ],
  },
  // Phase 4 starter — Rhino-flavored ops. Worker has full implementations;
  // inspector here uses the simplest field kinds. Loft + variable-radius-
  // fillet expose minimal v1 UIs; richer multi-profile reordering and
  // per-vertex-radius editors are follow-up polish.
  {
    op: 'sweep1',
    label: 'Sweep1',
    icon: Waves,
    defaults: { profile_sketch_path: '', path_sketch_path: '', twist_deg: 0, scale_end: 1, mode: 'auto' },
    fields: [
      { key: 'profile_sketch_path', kind: 'sketch_picker', label: 'Profile sketch' },
      { key: 'path_sketch_path', kind: 'sketch_picker', label: 'Path sketch' },
      { key: 'twist_deg', kind: 'number', label: 'Twist (°)', step: 1 },
      { key: 'scale_end', kind: 'number', label: 'End scale', min: 0.001, step: 0.05 },
      { key: 'mode', kind: 'select', label: 'Mode', options: [
        { value: 'auto', label: 'Auto' },
        { value: 'frenet', label: 'Frenet' },
        { value: 'corrected_frenet', label: 'Corrected Frenet' },
      ] },
    ],
  },
  {
    op: 'sweep2',
    label: 'Sweep2',
    icon: Waves,
    defaults: { profile_sketch_path: '', rail1_sketch_path: '', rail2_sketch_path: '', twist_deg: 0, scale_end: 1, mode: 'auto' },
    fields: [
      { key: 'profile_sketch_path', kind: 'sketch_picker', label: 'Profile sketch' },
      { key: 'rail1_sketch_path', kind: 'sketch_picker', label: 'Rail 1 sketch' },
      { key: 'rail2_sketch_path', kind: 'sketch_picker', label: 'Rail 2 sketch' },
      { key: 'twist_deg', kind: 'number', label: 'Twist (°)', step: 1 },
      { key: 'scale_end', kind: 'number', label: 'End scale', min: 0.001, step: 0.05 },
      { key: 'mode', kind: 'select', label: 'Mode', options: [
        { value: 'auto', label: 'Auto' },
        { value: 'frenet', label: 'Frenet' },
      ] },
    ],
  },
  {
    op: 'loft',
    label: 'Loft',
    icon: Layers3,
    defaults: { profile_sketch_paths: [], ruled: false, symmetric: false, closed: false, continuity: 'C0' },
    fields: [
      { key: 'profile_sketch_paths', kind: 'sketch_path_list', label: 'Profile sketches (≥2, ordered)' },
      { key: 'ruled', kind: 'bool', label: 'Ruled (linear blends)' },
      { key: 'symmetric', kind: 'bool', label: 'Symmetric (mid-plane)' },
      { key: 'closed', kind: 'bool', label: 'Closed loop (≥3 profiles)' },
      { key: 'continuity', kind: 'select', label: 'Continuity', options: [
        { value: 'C0', label: 'C0 (position)' },
        { value: 'C1', label: 'C1 (tangent)' },
        { value: 'C2', label: 'C2 (curvature)' },
      ] },
    ],
  },
  {
    op: 'variable_radius_fillet',
    label: 'Var. fillet',
    icon: Aperture,
    defaults: { target_id: '', edges: [] },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'edges', kind: 'edge_radius_list', label: 'Picked edges + radii' },
    ],
  },
  {
    op: 'network_srf',
    label: 'NetworkSrf',
    icon: Layers3,
    defaults: { u_curves: [], v_curves: [], continuity: 'C1' },
    fields: [
      { key: 'u_curves', kind: 'sketch_path_list', label: 'U-direction sketches (≥2)' },
      { key: 'v_curves', kind: 'sketch_path_list', label: 'V-direction sketches (≥2)' },
      { key: 'continuity', kind: 'select', label: 'Continuity', options: [
        { value: 'C0', label: 'C0 (position)' },
        { value: 'C1', label: 'C1 (tangent)' },
        { value: 'C2', label: 'C2 (curvature)' },
      ] },
    ],
  },
  {
    op: 'blend_srf',
    label: 'BlendSrf',
    icon: Waves,
    defaults: { target_id: '', edge1_id: -1, edge2_id: -1, continuity: 'G1' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
      { key: 'edge1_id', kind: 'number', label: 'Edge 1 id', step: 1 },
      { key: 'edge2_id', kind: 'number', label: 'Edge 2 id', step: 1 },
      { key: 'continuity', kind: 'select', label: 'Continuity', options: [
        { value: 'G0', label: 'G0 (position)' },
        { value: 'G1', label: 'G1 (tangent)' },
        { value: 'G2', label: 'G2 (curvature)' },
      ] },
    ],
  },
  // NURBS booleans v1 — T6: to_solid + boolean inspector entries
  {
    op: 'to_solid',
    label: 'To Solid',
    icon: Box,
    defaults: { target_id: '', tolerance: 1e-6 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Surface body to cap' },
      { key: 'tolerance', kind: 'number', label: 'Sewing tolerance (mm)', min: 1e-9, step: 1e-7 },
    ],
  },
  {
    op: 'boolean',
    label: 'Boolean',
    icon: Combine,
    defaults: { target_a_id: '', target_b_id: '', kind: 'cut' },
    fields: [
      { key: 'target_a_id', kind: 'feature_picker', label: 'A (kept on cut)' },
      { key: 'target_b_id', kind: 'feature_picker', label: 'B (subtracted on cut)' },
      { key: 'kind', kind: 'select', label: 'Operation', options: [
        { value: 'cut',    label: 'Cut (A − B)' },
        { value: 'fuse',   label: 'Fuse (A ∪ B)' },
        { value: 'common', label: 'Common (A ∩ B)' },
      ] },
    ],
  },
  // NURBS Phase 4 C1-T4 — surface_boolean inspector entry.
  //
  // Conceptual sibling to `boolean` (solid CSG) but works directly on
  // Face / Shell / Solid operands — no feature_to_solid pre-step needed.
  // Returns a compound of trimmed face fragments rather than a closed solid.
  // Ideal for jewelry-CAD surface-direct workflows (blend cut by sweep, etc.).
  //
  // Differences vs `boolean`:
  //   - Accepts any topology (Face / Shell / Solid) — no solid enforcement.
  //   - Returns a compound of trimmed fragments, not a closed solid.
  //   - `tolerance` tunes the BOPAlgo intersection tolerance (fuzziness).
  //   - `fuzzy_value` passes directly to BRepAlgoAPI_*::SetFuzzyValue when
  //     the binding exposes it; raise to 1e-3 if tangent-intersection face
  //     fragments go missing.
  //   - If the worker logs a C1-T10 escalation, the current WASM build does
  //     not support non-solid operands — fall back to feature_boolean with a
  //     feature_to_solid pre-pass.
  {
    op: 'surface_boolean',
    label: 'SurfaceBoolean',
    icon: Combine,
    defaults: { target_a_id: '', target_b_id: '', kind: 'cut', tolerance: 1e-3 },
    caption: (
      'Surface-direct boolean — accepts Face/Shell/Solid operands without a ' +
      'feature_to_solid pre-step. Returns trimmed face fragments. ' +
      'Use when operating on raw NURBS surfaces (sweeps, blends, networks). ' +
      'For solid-on-solid CSG use the regular Boolean op instead.'
    ),
    fields: [
      { key: 'target_a_id', kind: 'feature_picker', label: 'A (surface/solid, kept on cut)' },
      { key: 'target_b_id', kind: 'feature_picker', label: 'B (surface/solid, tool on cut)' },
      { key: 'kind', kind: 'select', label: 'Operation', options: [
        { value: 'cut',    label: 'Cut (A − B)' },
        { value: 'fuse',   label: 'Fuse (A ∪ B)' },
        { value: 'common', label: 'Common (A ∩ B)' },
      ] },
      { key: 'tolerance', kind: 'number', label: 'Tolerance (mm)', min: 1e-9, step: 1e-4 },
      { key: 'fuzzy_value', kind: 'number', label: 'Fuzzy value (optional)', min: 0, step: 1e-4 },
    ],
  },
  // NURBS Phase 4 C2-T7/GK-P41 — trim_by_curve inspector entry.
  //
  // Projects a 3D cutter curve onto a NURBS face and splits it, keeping one
  // side. surface-direct trim — no solid round-trip needed.
  // Params: target feature body ref, face name (positional face-N), curve ref
  // (.sketch path or feature id), keep_side (positive/negative), tolerance.
  // WARNING: trim invalidates positional face-N IDs — re-identify faces in the
  // inspector after a trim step.
  {
    op: 'trim_by_curve',
    label: 'TrimByCurve',
    icon: Crosshair,
    caption: (
      'Project a 3D curve onto a NURBS face and split it, keeping one side. ' +
      'WARNING: trim invalidates positional face-N IDs — re-identify faces in ' +
      'the inspector after trimming. Use keep_side to pick the half to retain.'
    ),
    defaults: {
      target_feature_ref: '',
      target_face_name: 'face-1',
      trim_curve_ref: '',
      keep_side: 'positive',
      tolerance: 1e-3,
    },
    fields: [
      { key: 'target_feature_ref', kind: 'feature_picker', label: 'Target body' },
      { key: 'target_face_name',   kind: 'text',           label: 'Face name (e.g. face-1)' },
      { key: 'trim_curve_ref',     kind: 'sketch_picker',  label: 'Trim curve (.sketch or feature id)' },
      { key: 'keep_side', kind: 'select', label: 'Keep side', options: [
        { value: 'positive', label: 'Positive (Left)' },
        { value: 'negative', label: 'Negative (Right)' },
      ] },
      { key: 'tolerance', kind: 'number', label: 'Projection tolerance (mm)', min: 1e-9, step: 1e-4 },
    ],
  },
  // Slicing v0.2 — plane cross-section via BRepAlgoAPI_Section.
  // Returns a compound of intersection edges (1D outline, not a solid).
  // Inspector: target solid picker + plane point/normal xyz inputs.
  // Section-plane gumball is deferred to v0.3 (TODO: add drag-to-reposition
  // gumball in Gumball.jsx that snaps to face plane when armed).
  {
    op: 'section',
    label: 'Section',
    icon: Scissors,
    defaults: {
      target_solid_ref: '',
      plane: { point: [0, 0, 0], normal: [0, 0, 1] },
    },
    fields: [
      { key: 'target_solid_ref', kind: 'feature_picker', label: 'Target solid' },
      { key: 'plane.point[0]',  kind: 'number', label: 'Plane point X (mm)' },
      { key: 'plane.point[1]',  kind: 'number', label: 'Plane point Y (mm)' },
      { key: 'plane.point[2]',  kind: 'number', label: 'Plane point Z (mm)' },
      { key: 'plane.normal[0]', kind: 'number', label: 'Normal X' },
      { key: 'plane.normal[1]', kind: 'number', label: 'Normal Y' },
      { key: 'plane.normal[2]', kind: 'number', label: 'Normal Z' },
    ],
  },
  // Quad remesh v1 — Instant Meshes subprocess (MIT).
  // Remeshes a triangle mesh into a quad-dominant topology.
  // Requires the `instant-meshes` binary on PATH; degrades gracefully when absent.
  {
    op: 'quad_remesh',
    label: 'Quad Remesh',
    icon: Grid3x3,
    defaults: {
      target_feature_ref:  '',
      target_vertex_count: 5000,
      crease_angle_deg:    20,
      align_to_boundary:   true,
      smoothness_iters:    2,
    },
    fields: [
      { key: 'target_feature_ref',  kind: 'feature_picker', label: 'Source mesh / solid' },
      { key: 'target_vertex_count', kind: 'number', label: 'Target vertex count',   min: 1, step: 500 },
      { key: 'crease_angle_deg',    kind: 'number', label: 'Crease angle (°)',       min: 0, max: 180, step: 1 },
      { key: 'smoothness_iters',    kind: 'number', label: 'Smoothing iterations',  min: 0, max: 6, step: 1 },
      { key: 'align_to_boundary',   kind: 'boolean', label: 'Align to boundary' },
    ],
  },
  // Jewelry settings — prong head, bezel, channel, pavé.
  // Stone setting generators for production jewelry CAD workflows.
  {
    op: 'jewelry_prong_head',
    label: 'Prong Head',
    icon: Circle,
    defaults: {
      stone_diameter: 6.5,
      prong_count: 6,
      prong_wire_diameter: 1.0,
      prong_height: 2.0,
      head_style: 'standard',
      basket_rail_count: 1,
      seat_angle_deg: 15,
    },
    fields: [
      { key: 'stone_diameter',      kind: 'number', label: 'Stone diameter (mm)',      min: 0.1, step: 0.1 },
      { key: 'prong_count',         kind: 'select', label: 'Prong count', options: [
        { value: 4, label: '4-prong' },
        { value: 6, label: '6-prong' },
      ] },
      { key: 'prong_wire_diameter', kind: 'number', label: 'Prong wire dia. (mm)',     min: 0.1, step: 0.05 },
      { key: 'prong_height',        kind: 'number', label: 'Prong height (mm)',        min: 0.1, step: 0.1 },
      { key: 'head_style',          kind: 'select', label: 'Head style', options: [
        { value: 'standard',  label: 'Standard' },
        { value: 'basket',    label: 'Basket' },
        { value: 'trellis',   label: 'Trellis' },
        { value: 'cathedral', label: 'Cathedral' },
      ] },
      { key: 'basket_rail_count', kind: 'number', label: 'Basket rail count', min: 0, step: 1 },
      { key: 'seat_angle_deg',    kind: 'number', label: 'Seat angle (°)',    min: 1, max: 45, step: 1 },
    ],
  },
  {
    op: 'jewelry_bezel',
    label: 'Bezel',
    icon: Circle,
    defaults: {
      stone_diameter: 6.5,
      wall_thickness: 0.5,
      bezel_height: 3.0,
      bearing_ledge_height: 1.2,
      bezel_style: 'full',
      partial_opening_deg: 60,
      taper_angle_deg: 0,
    },
    fields: [
      { key: 'stone_diameter',       kind: 'number', label: 'Stone diameter (mm)',    min: 0.1, step: 0.1 },
      { key: 'wall_thickness',       kind: 'number', label: 'Wall thickness (mm)',    min: 0.1, step: 0.05 },
      { key: 'bezel_height',         kind: 'number', label: 'Bezel height (mm)',      min: 0.1, step: 0.1 },
      { key: 'bearing_ledge_height', kind: 'number', label: 'Bearing ledge ht. (mm)', min: 0.05, step: 0.05 },
      { key: 'bezel_style',          kind: 'select', label: 'Style', options: [
        { value: 'full',    label: 'Full' },
        { value: 'partial', label: 'Partial' },
        { value: 'collet',  label: 'Collet' },
        { value: 'tapered', label: 'Tapered' },
      ] },
      { key: 'partial_opening_deg', kind: 'number', label: 'Opening angle (°)', min: 1, max: 359, step: 5,
        showWhen: (n) => n.bezel_style === 'partial' },
      { key: 'taper_angle_deg', kind: 'number', label: 'Taper angle (°)', min: 0, max: 30, step: 1,
        showWhen: (n) => n.bezel_style === 'tapered' || n.bezel_style === 'collet' },
    ],
  },
  {
    op: 'jewelry_channel',
    label: 'Channel',
    icon: Layers,
    defaults: {
      stone_diameter: 2.5,
      stone_count: 7,
      stone_spacing: 2.8,
      rail_height: 1.5,
      rail_thickness: 0.5,
      floor_thickness: 0.4,
    },
    fields: [
      { key: 'stone_diameter',  kind: 'number', label: 'Stone diameter (mm)', min: 0.1, step: 0.1 },
      { key: 'stone_count',     kind: 'number', label: 'Stone count',         min: 1, step: 1 },
      { key: 'stone_spacing',   kind: 'number', label: 'C-to-C spacing (mm)', min: 0.1, step: 0.05 },
      { key: 'rail_height',     kind: 'number', label: 'Rail height (mm)',    min: 0.1, step: 0.1 },
      { key: 'rail_thickness',  kind: 'number', label: 'Rail thickness (mm)', min: 0.1, step: 0.05 },
      { key: 'floor_thickness', kind: 'number', label: 'Floor thickness (mm)', min: 0.1, step: 0.05 },
    ],
  },
  {
    op: 'jewelry_pave',
    label: 'Pavé Array',
    icon: LayoutGrid,
    defaults: {
      region_width: 10.0,
      region_height: 10.0,
      stone_diameter: 1.5,
      stone_spacing: 0.2,
      edge_margin: 0.5,
      surface_normal: [0, 0, 1],
      surface_origin: [0, 0, 0],
    },
    fields: [
      { key: 'region_width',   kind: 'number', label: 'Region width (mm)',   min: 0.1, step: 0.5 },
      { key: 'region_height',  kind: 'number', label: 'Region height (mm)',  min: 0.1, step: 0.5 },
      { key: 'stone_diameter', kind: 'number', label: 'Stone diameter (mm)', min: 0.1, step: 0.05 },
      { key: 'stone_spacing',  kind: 'number', label: 'Stone spacing (mm)',  min: 0, step: 0.05 },
      { key: 'edge_margin',    kind: 'number', label: 'Edge margin (mm)',    min: 0, step: 0.1 },
    ],
  },
  // NURBS Phase 4 C4 — curvature comb overlay (visualisation-only).
  // GeomAbs_G3 doesn't exist in stock OCCT — overlay lets users EYEBALL
  // G3 continuity at face junctions instead of enforcing it algorithmically.
  {
    op: 'surface_curvature_combs',
    label: 'CurvatureCombs',
    icon: Waves,
    defaults: {
      target_feature_ref: '',
      target_face_name: '',
      uv_density: 0.1,
      scale_factor: 10,
      show_combs: true,
    },
    caption: (
      'Curvature-comb overlay — renders principal-curvature combs on NURBS faces ' +
      '(blue=concave, red=convex, white=flat). ' +
      'Use to eyeball G2/G3 continuity at face junctions. ' +
      'Viz-only: stock OCCT has no GeomAbs_G3.'
    ),
    fields: [
      { key: 'target_feature_ref', kind: 'feature_picker', label: 'Target surface/solid' },
      { key: 'target_face_name',   kind: 'text',    label: 'Face name (blank = all faces)' },
      { key: 'uv_density',         kind: 'number',  label: 'UV density', min: 0.01, max: 0.5, step: 0.01 },
      { key: 'scale_factor',       kind: 'number',  label: 'Scale factor', min: 0.1, step: 1 },
      { key: 'show_combs',         kind: 'boolean', label: 'Show combs' },
    ],
  },
  // ── Jewelry ──────────────────────────────────────────────────────────────
  {
    op: 'gemstone',
    label: 'Gemstone',
    icon: Disc,
    defaults: {
      cut: 'round_brilliant',
      diameter_mm: 6.5,
      material: 'diamond',
    },
    fields: [
      { key: 'cut', kind: 'select', label: 'Cut', options: [
        { value: 'round_brilliant',  label: 'Round brilliant' },
        { value: 'princess',         label: 'Princess' },
        { value: 'oval',             label: 'Oval' },
        { value: 'emerald',          label: 'Emerald' },
        { value: 'marquise',         label: 'Marquise' },
        { value: 'pear',             label: 'Pear' },
        { value: 'cushion',          label: 'Cushion' },
        { value: 'radiant',          label: 'Radiant' },
        { value: 'asscher',          label: 'Asscher' },
        { value: 'trillion',         label: 'Trillion' },
        { value: 'heart',            label: 'Heart' },
        { value: 'baguette',         label: 'Baguette' },
        { value: 'briolette',        label: 'Briolette' },
        { value: 'old_european',     label: 'Old European' },
        { value: 'old_mine',         label: 'Old Mine' },
        { value: 'rose_cut',         label: 'Rose cut' },
        { value: 'single_cut',       label: 'Single cut' },
        { value: 'french_cut',       label: 'French cut' },
        { value: 'half_moon',        label: 'Half moon' },
        { value: 'trapezoid',        label: 'Trapezoid' },
        { value: 'kite',             label: 'Kite' },
        { value: 'bullet',           label: 'Bullet' },
        { value: 'tapered_baguette', label: 'Tapered baguette' },
        { value: 'lozenge',          label: 'Lozenge' },
        { value: 'shield',           label: 'Shield' },
        { value: 'calf_head',        label: 'Calf head' },
        { value: 'portuguese',       label: 'Portuguese' },
        { value: 'ceylon',           label: 'Ceylon' },
        { value: 'flanders',         label: 'Flanders' },
        { value: 'square_emerald',   label: 'Square emerald' },
      ] },
      { key: 'diameter_mm',         kind: 'number',  label: 'Diameter / long-axis (mm)', min: 0.5 },
      { key: 'material',            kind: 'text',    label: 'Material' },
      { key: 'table_pct',           kind: 'number',  label: 'Table %',        min: 30, max: 90 },
      { key: 'crown_angle_deg',     kind: 'number',  label: 'Crown angle (°)', min: 10, max: 50 },
      { key: 'pavilion_angle_deg',  kind: 'number',  label: 'Pavilion angle (°)', min: 30, max: 55 },
      { key: 'girdle_pct',          kind: 'number',  label: 'Girdle %',        min: 0.5, max: 10 },
    ],
  },
  {
    op: 'gem_seat',
    label: 'Gem seat',
    icon: Disc,
    defaults: {
      cut: 'round_brilliant',
      diameter_mm: 6.5,
      girdle_clearance_mm: 0.05,
      through_hole: false,
    },
    caption: (
      'Gem-seat cutter solid: bearing cone + girdle ledge + crown relief. ' +
      'Subtract from host solid with a boolean cut to set the stone.'
    ),
    fields: [
      { key: 'cut', kind: 'select', label: 'Cut', options: [
        { value: 'round_brilliant',  label: 'Round brilliant' },
        { value: 'princess',         label: 'Princess' },
        { value: 'oval',             label: 'Oval' },
        { value: 'emerald',          label: 'Emerald' },
        { value: 'marquise',         label: 'Marquise' },
        { value: 'pear',             label: 'Pear' },
        { value: 'cushion',          label: 'Cushion' },
        { value: 'radiant',          label: 'Radiant' },
        { value: 'asscher',          label: 'Asscher' },
        { value: 'trillion',         label: 'Trillion' },
        { value: 'heart',            label: 'Heart' },
        { value: 'baguette',         label: 'Baguette' },
        { value: 'briolette',        label: 'Briolette' },
        { value: 'old_european',     label: 'Old European' },
        { value: 'old_mine',         label: 'Old Mine' },
        { value: 'rose_cut',         label: 'Rose cut' },
        { value: 'single_cut',       label: 'Single cut' },
        { value: 'french_cut',       label: 'French cut' },
        { value: 'half_moon',        label: 'Half moon' },
        { value: 'trapezoid',        label: 'Trapezoid' },
        { value: 'kite',             label: 'Kite' },
        { value: 'bullet',           label: 'Bullet' },
        { value: 'tapered_baguette', label: 'Tapered baguette' },
        { value: 'lozenge',          label: 'Lozenge' },
        { value: 'shield',           label: 'Shield' },
        { value: 'calf_head',        label: 'Calf head' },
        { value: 'portuguese',       label: 'Portuguese' },
        { value: 'ceylon',           label: 'Ceylon' },
        { value: 'flanders',         label: 'Flanders' },
        { value: 'square_emerald',   label: 'Square emerald' },
      ] },
      { key: 'diameter_mm',          kind: 'number',  label: 'Diameter / long-axis (mm)', min: 0.5 },
      { key: 'girdle_clearance_mm',  kind: 'number',  label: 'Girdle clearance (mm)', min: 0, step: 0.01 },
      { key: 'culet_clearance_mm',   kind: 'number',  label: 'Culet clearance (mm)',  min: 0, step: 0.01 },
      { key: 'crown_relief_mm',      kind: 'number',  label: 'Crown relief (mm)',     min: 0, step: 0.05 },
      { key: 'through_hole',         kind: 'boolean', label: 'Through-hole for light' },
    ],
  },
  // Ring shank builder: swept band along the finger circle.
  // Size is auto-converted to inner diameter; profile/shoulder control
  // the cross-section shape and how the band meets the setting.
  {
    op: 'ring_shank',
    label: 'Ring Shank',
    icon: Circle,
    defaults: {
      ring_size: 7,
      system: 'us',
      band_width: 4.0,
      thickness: 1.8,
      profile: 'comfort_fit',
      taper_ratio: 1.0,
      shoulder_style: 'plain',
    },
    caption: (
      'Parametric ring band swept along the finger circle. ' +
      'Profile controls the cross-section shape; shoulder_style controls ' +
      'how the band meets a head/setting (plain, cathedral, split_shank, bypass). ' +
      'All dimensions in mm; ring_size auto-converts to inner diameter.'
    ),
    fields: [
      { key: 'ring_size', kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system', kind: 'select', label: 'Size system', options: [
        { value: 'us',  label: 'US (0–16)' },
        { value: 'uk',  label: 'UK / AU (A–Z+)' },
        { value: 'eu',  label: 'EU (circumference mm)' },
        { value: 'jp',  label: 'JP (1–30)' },
      ] },
      { key: 'band_width', kind: 'number', label: 'Band width (mm)', min: 0.1, step: 0.5 },
      { key: 'thickness',  kind: 'number', label: 'Wall thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'profile', kind: 'select', label: 'Profile', options: [
        { value: 'comfort_fit', label: 'Comfort fit (rounded inside)' },
        { value: 'd_shape',     label: 'D-shape (flat outside)' },
        { value: 'flat',        label: 'Flat' },
        { value: 'half_round',  label: 'Half round' },
        { value: 'knife_edge',  label: 'Knife edge' },
        { value: 'euro',        label: 'Euro (square-ish)' },
        { value: 'tapered',     label: 'Tapered' },
      ] },
      { key: 'taper_ratio', kind: 'number', label: 'Taper ratio (1=uniform)', min: 0.1, max: 1.0, step: 0.05 },
      { key: 'shoulder_style', kind: 'select', label: 'Shoulder style', options: [
        { value: 'plain',       label: 'Plain' },
        { value: 'cathedral',   label: 'Cathedral' },
        { value: 'split_shank', label: 'Split shank' },
        { value: 'bypass',      label: 'Bypass' },
      ] },
    ],
  },
  // ── Jewelry settings v1–v2 (tension, flush, halo, three-stone, cluster, bar, bead, gypsy, illusion, invisible) ──

  {
    op: 'jewelry_tension',
    label: 'Tension Setting',
    icon: Circle,
    defaults: { stone_diameter: 6.5, band_thickness: 3.0, gap: 5.5, rail_width: 0.5, rail_depth: 0.3 },
    fields: [
      { key: 'stone_diameter', kind: 'number', label: 'Stone diameter (mm)', min: 0.1, step: 0.1 },
      { key: 'band_thickness', kind: 'number', label: 'Band thickness (mm)',  min: 0.1, step: 0.1 },
      { key: 'gap',            kind: 'number', label: 'Gap between ends (mm)', min: 0.1, step: 0.1 },
      { key: 'rail_width',     kind: 'number', label: 'Rail width (mm)',       min: 0.1, step: 0.05 },
      { key: 'rail_depth',     kind: 'number', label: 'Rail depth (mm)',       min: 0.1, step: 0.05 },
    ],
  },
  {
    op: 'jewelry_flush',
    label: 'Flush / Gypsy',
    icon: Disc,
    defaults: { stone_diameter: 4.0, seat_depth: 2.0, bevel_width: 0.2, bevel_angle_deg: 45 },
    caption: 'Flush (gypsy) setting — drilled seat + chamfered opening. Subtract from host solid with a boolean cut.',
    fields: [
      { key: 'stone_diameter',  kind: 'number', label: 'Stone diameter (mm)', min: 0.1, step: 0.1 },
      { key: 'seat_depth',      kind: 'number', label: 'Seat depth (mm)',      min: 0.1, step: 0.1 },
      { key: 'bevel_width',     kind: 'number', label: 'Bevel width (mm)',     min: 0.05, step: 0.05 },
      { key: 'bevel_angle_deg', kind: 'number', label: 'Bevel angle (°)',      min: 1, max: 89, step: 1 },
    ],
  },
  {
    op: 'jewelry_halo',
    label: 'Halo Setting',
    icon: Disc,
    defaults: { center_diameter: 6.5, halo_stone_size: 1.3, halo_stone_count: 18, halo_gap: 0.2, halo_metal_width: 0.4 },
    caption: 'Halo — ring of accent stones around a center seat. Add a prong head or bezel for the center stone separately.',
    fields: [
      { key: 'center_diameter',    kind: 'number', label: 'Center stone dia. (mm)', min: 0.5, step: 0.1 },
      { key: 'halo_stone_size',    kind: 'number', label: 'Accent stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'halo_stone_count',   kind: 'number', label: 'Accent stone count',     min: 3, step: 1 },
      { key: 'halo_gap',           kind: 'number', label: 'Gap center→halo (mm)',   min: 0, step: 0.05 },
      { key: 'halo_metal_width',   kind: 'number', label: 'Halo frame width (mm)',  min: 0.1, step: 0.05 },
    ],
  },
  {
    op: 'jewelry_three_stone',
    label: 'Three Stone',
    icon: Layers,
    defaults: { center_diameter: 6.5, side_diameter: 4.0, stone_spacing: 0.2, base_height: 3.0 },
    fields: [
      { key: 'center_diameter', kind: 'number', label: 'Center stone dia. (mm)', min: 0.5, step: 0.1 },
      { key: 'side_diameter',   kind: 'number', label: 'Side stone dia. (mm)',   min: 0.5, step: 0.1 },
      { key: 'stone_spacing',   kind: 'number', label: 'Stone gap (mm)',          min: 0, step: 0.05 },
      { key: 'base_height',     kind: 'number', label: 'Gallery base height (mm)', min: 0.1, step: 0.1 },
    ],
  },
  {
    op: 'jewelry_cluster',
    label: 'Cluster',
    icon: LayoutGrid,
    defaults: { cluster_diameter: 10.0, stone_size: 1.5, stone_count: 7, dome_height: 1.0 },
    fields: [
      { key: 'cluster_diameter', kind: 'number', label: 'Cluster diameter (mm)', min: 0.1, step: 0.5 },
      { key: 'stone_size',       kind: 'number', label: 'Stone size (mm)',        min: 0.1, step: 0.1 },
      { key: 'stone_count',      kind: 'number', label: 'Stone count',            min: 1, step: 1 },
      { key: 'dome_height',      kind: 'number', label: 'Dome height (mm)',       min: 0, step: 0.1 },
    ],
  },
  {
    op: 'jewelry_bar',
    label: 'Bar Setting',
    icon: Layers,
    defaults: { stone_diameter: 2.5, bar_width: 0.6, bar_height: 0.8, stone_count: 5, pitch: 3.0 },
    fields: [
      { key: 'stone_diameter', kind: 'number', label: 'Stone dia. (mm)',       min: 0.1, step: 0.1 },
      { key: 'bar_width',      kind: 'number', label: 'Bar width (mm)',        min: 0.1, step: 0.05 },
      { key: 'bar_height',     kind: 'number', label: 'Bar height (mm)',       min: 0.1, step: 0.1 },
      { key: 'stone_count',    kind: 'number', label: 'Stone count',           min: 1, step: 1 },
      { key: 'pitch',          kind: 'number', label: 'C-to-C pitch (mm)',     min: 0.1, step: 0.1 },
    ],
  },
  {
    op: 'jewelry_bead_grain',
    label: 'Bead / Grain',
    icon: LayoutGrid,
    defaults: { stone_diameter: 2.0, bead_count_per_stone: 4, bead_diameter: 0.5, field_layout: 'line' },
    fields: [
      { key: 'stone_diameter',       kind: 'number', label: 'Stone dia. (mm)',          min: 0.1, step: 0.1 },
      { key: 'bead_count_per_stone', kind: 'number', label: 'Beads per stone',          min: 2, step: 1 },
      { key: 'bead_diameter',        kind: 'number', label: 'Bead dia. (mm)',           min: 0.1, step: 0.05 },
      { key: 'field_layout', kind: 'select', label: 'Layout', options: [
        { value: 'line', label: 'Line (single row)' },
        { value: 'grid', label: 'Grid (rectangular)' },
      ] },
    ],
  },
  {
    op: 'jewelry_gypsy_pave',
    label: 'Gypsy Pavé',
    icon: Disc,
    defaults: { stone_diameter: 3.0, seat_depth: 1.5, star_ray_count: 8 },
    caption: 'Gypsy-pavé (star setting) — flush seat + V-cut star rays. Minimum 4 rays.',
    fields: [
      { key: 'stone_diameter',  kind: 'number', label: 'Stone dia. (mm)',  min: 0.1, step: 0.1 },
      { key: 'seat_depth',      kind: 'number', label: 'Seat depth (mm)',  min: 0.1, step: 0.1 },
      { key: 'star_ray_count',  kind: 'number', label: 'Star ray count',   min: 4, step: 1 },
    ],
  },
  {
    op: 'jewelry_illusion',
    label: 'Illusion',
    icon: Disc,
    defaults: { stone_diameter: 3.0, plate_diameter: 8.0, facet_count: 12 },
    caption: 'Illusion (miracle-plate) setting — faceted metal plate makes a small stone appear larger.',
    fields: [
      { key: 'stone_diameter',  kind: 'number', label: 'Stone dia. (mm)',    min: 0.1, step: 0.1 },
      { key: 'plate_diameter',  kind: 'number', label: 'Plate dia. (mm)',    min: 0.2, step: 0.1 },
      { key: 'facet_count',     kind: 'number', label: 'Plate facet count',  min: 4, step: 1 },
    ],
  },
  {
    op: 'jewelry_invisible',
    label: 'Invisible Setting',
    icon: LayoutGrid,
    defaults: { stone_size: 3.0, rail_width: 0.3, rail_height: 1.0, grid_rows: 2, grid_cols: 3 },
    caption: 'Invisible setting — princess stones on concealed rails; no visible metal between stones.',
    fields: [
      { key: 'stone_size',   kind: 'number', label: 'Stone side (mm)',   min: 0.1, step: 0.1 },
      { key: 'rail_width',   kind: 'number', label: 'Rail width (mm)',   min: 0.1, step: 0.05 },
      { key: 'rail_height',  kind: 'number', label: 'Rail height (mm)',  min: 0.1, step: 0.1 },
      { key: 'grid_rows',    kind: 'number', label: 'Grid rows',         min: 1, step: 1 },
      { key: 'grid_cols',    kind: 'number', label: 'Grid columns',      min: 1, step: 1 },
    ],
  },

  // ── Jewelry settings v3–v4 ──────────────────────────────────────────────

  {
    op: 'jewelry_prong_variant',
    label: 'Prong Variant',
    icon: Circle,
    defaults: { variant: 'double_prong', stone_diameter: 6.5, prong_count: 6, wire_gauge: 1.0, prong_height: 2.0, variant_param: 0.0, variant_profile: 'round' },
    fields: [
      { key: 'variant', kind: 'select', label: 'Variant', options: [
        { value: 'double_prong',    label: 'Double prong' },
        { value: 'claw_prong',      label: 'Claw prong' },
        { value: 'v_prong',         label: 'V prong (pointed stones)' },
        { value: 'fishtail_prong',  label: 'Fishtail prong' },
        { value: 'split_prong',     label: 'Split prong' },
        { value: 'decorative_prong',label: 'Decorative prong' },
      ] },
      { key: 'stone_diameter', kind: 'number', label: 'Stone dia. (mm)',    min: 0.1, step: 0.1 },
      { key: 'prong_count',    kind: 'number', label: 'Prong count',        min: 2, step: 1 },
      { key: 'wire_gauge',     kind: 'number', label: 'Wire gauge (mm)',     min: 0.1, step: 0.05 },
      { key: 'prong_height',   kind: 'number', label: 'Prong height (mm)',   min: 0.1, step: 0.1 },
      { key: 'variant_param',  kind: 'number', label: 'Variant param',       min: 0, step: 0.05 },
      { key: 'variant_profile', kind: 'select', label: 'Decorative profile',
        showWhen: (n) => n.variant === 'decorative_prong',
        options: [
          { value: 'round',    label: 'Round' },
          { value: 'tapered',  label: 'Tapered' },
          { value: 'filigree', label: 'Filigree' },
          { value: 'star',     label: 'Star' },
          { value: 'leaf',     label: 'Leaf' },
        ],
      },
    ],
  },
  {
    op: 'jewelry_head_gallery',
    label: 'Head + Gallery',
    icon: Circle,
    defaults: { head_diameter: 8.0, head_height: 3.0, gallery_height: 1.5, gallery_style: 'plain', motif_pitch: 0 },
    fields: [
      { key: 'head_diameter',   kind: 'number', label: 'Head diameter (mm)',  min: 0.1, step: 0.1 },
      { key: 'head_height',     kind: 'number', label: 'Head height (mm)',    min: 0.1, step: 0.1 },
      { key: 'gallery_height',  kind: 'number', label: 'Gallery height (mm)', min: 0.1, step: 0.1 },
      { key: 'gallery_style', kind: 'select', label: 'Gallery style', options: [
        { value: 'plain',        label: 'Plain' },
        { value: 'scalloped',    label: 'Scalloped' },
        { value: 'milgrain_edge',label: 'Milgrain edge' },
        { value: 'pierced',      label: 'Pierced' },
        { value: 'filigree',     label: 'Filigree' },
      ] },
      { key: 'motif_pitch', kind: 'number', label: 'Motif pitch (mm)', min: 0, step: 0.1,
        showWhen: (n) => n.gallery_style !== 'plain' },
    ],
  },
  {
    op: 'jewelry_under_bezel',
    label: 'Under-Bezel',
    icon: Circle,
    defaults: { stone_diameter: 6.5, wall_thickness: 0.5, collet_height: 2.0, base_diameter: 9.0, base_thickness: 0.5 },
    caption: 'Sub-collet: raises the stone above the shank. Use as a secondary support under bezels or halos.',
    fields: [
      { key: 'stone_diameter',  kind: 'number', label: 'Stone dia. (mm)',    min: 0.1, step: 0.1 },
      { key: 'wall_thickness',  kind: 'number', label: 'Wall thickness (mm)', min: 0.1, step: 0.05 },
      { key: 'collet_height',   kind: 'number', label: 'Collet height (mm)', min: 0.1, step: 0.1 },
      { key: 'base_diameter',   kind: 'number', label: 'Base dia. (mm)',     min: 0.1, step: 0.1 },
      { key: 'base_thickness',  kind: 'number', label: 'Base thickness (mm)', min: 0.1, step: 0.05 },
    ],
  },
  {
    op: 'jewelry_peg_setting',
    label: 'Peg Setting',
    icon: Circle,
    defaults: { stone_diameter: 5.0, peg_diameter: 1.0, peg_length: 10.0, base_diameter: 3.0, base_thickness: 0.5 },
    caption: 'Peg (post) setting for earrings and pendants — cylindrical post with stone cup at top.',
    fields: [
      { key: 'stone_diameter', kind: 'number', label: 'Stone dia. (mm)',  min: 0.1, step: 0.1 },
      { key: 'peg_diameter',   kind: 'number', label: 'Peg dia. (mm)',    min: 0.1, step: 0.05 },
      { key: 'peg_length',     kind: 'number', label: 'Peg length (mm)',  min: 0.1, step: 0.5 },
      { key: 'base_diameter',  kind: 'number', label: 'Base dia. (mm)',   min: 0.1, step: 0.1 },
      { key: 'base_thickness', kind: 'number', label: 'Base thick. (mm)', min: 0.1, step: 0.05 },
    ],
  },
  {
    op: 'jewelry_coronet',
    label: 'Coronet',
    icon: Circle,
    defaults: { stone_diameter: 6.5, prong_count: 8, crown_height: 3.0, taper: 0.3, wire_gauge: 1.0 },
    caption: 'Crown (coronet) setting — tapered prong wires lean inward for a regal Victorian silhouette.',
    fields: [
      { key: 'stone_diameter', kind: 'number', label: 'Stone dia. (mm)',   min: 0.1, step: 0.1 },
      { key: 'prong_count',    kind: 'number', label: 'Prong count',       min: 3, step: 1 },
      { key: 'crown_height',   kind: 'number', label: 'Crown height (mm)', min: 0.1, step: 0.1 },
      { key: 'taper',          kind: 'number', label: 'Inward taper (mm)', min: 0, step: 0.05 },
      { key: 'wire_gauge',     kind: 'number', label: 'Wire gauge (mm)',   min: 0.1, step: 0.05 },
    ],
  },
  {
    op: 'jewelry_suspension_mount',
    label: 'Suspension Mount',
    icon: Circle,
    defaults: { stone_diameter: 5.0, seat_style: 'bezel_cup', seat_depth: 2.0, ring_wire_diameter: 1.0, ring_inner_diameter: 3.0, bail_height: 2.0 },
    caption: 'Articulated dangle mount for drop earrings and pendants — seat + pivot jump-ring.',
    fields: [
      { key: 'stone_diameter',     kind: 'number', label: 'Stone dia. (mm)',         min: 0.1, step: 0.1 },
      { key: 'seat_style', kind: 'select', label: 'Seat style', options: [
        { value: 'bezel_cup', label: 'Bezel cup' },
        { value: 'prong_cup', label: 'Prong cup (4 prongs)' },
        { value: 'claw_cup',  label: 'Claw cup' },
      ] },
      { key: 'seat_depth',         kind: 'number', label: 'Seat depth (mm)',         min: 0.1, step: 0.1 },
      { key: 'ring_wire_diameter', kind: 'number', label: 'Ring wire dia. (mm)',     min: 0.1, step: 0.05 },
      { key: 'ring_inner_diameter',kind: 'number', label: 'Ring inner dia. (mm)',    min: 0.1, step: 0.1 },
      { key: 'bail_height',        kind: 'number', label: 'Bail height (mm)',        min: 0.1, step: 0.1 },
    ],
  },
  {
    op: 'jewelry_vtip_protector',
    label: 'V-Tip Protector',
    icon: Circle,
    defaults: { stone_shape: 'pear', tip_count: 1, tip_width: 0.6, tip_length: 1.0, wall_thickness: 0.3, seat_angle_deg: 55 },
    caption: 'V-tip metal caps for pointed fancy-cut stones (pear, marquise, heart, trillion) — prevent chipping.',
    fields: [
      { key: 'stone_shape', kind: 'select', label: 'Stone shape', options: [
        { value: 'pear',     label: 'Pear' },
        { value: 'marquise', label: 'Marquise' },
        { value: 'heart',    label: 'Heart' },
        { value: 'trillion', label: 'Trillion' },
      ] },
      { key: 'tip_count',       kind: 'number', label: 'Tip count',          min: 1, step: 1 },
      { key: 'tip_width',       kind: 'number', label: 'Tip width (mm)',     min: 0.1, step: 0.05 },
      { key: 'tip_length',      kind: 'number', label: 'Tip length (mm)',    min: 0.1, step: 0.1 },
      { key: 'wall_thickness',  kind: 'number', label: 'Wall thick. (mm)',   min: 0.1, step: 0.05 },
      { key: 'seat_angle_deg',  kind: 'number', label: 'Seat angle (°)',     min: 1, max: 179, step: 1 },
    ],
  },
  {
    op: 'jewelry_bombe_cluster',
    label: 'Bombé Cluster',
    icon: LayoutGrid,
    defaults: { dome_radius: 8.0, stone_size: 1.5, stone_count: 12, cap_half_angle_deg: 60, base_height: 1.0 },
    caption: 'Bombé (dome) cluster — stones distributed over a spherical-cap surface via Fibonacci spiral.',
    fields: [
      { key: 'dome_radius',         kind: 'number', label: 'Dome radius (mm)',        min: 0.1, step: 0.5 },
      { key: 'stone_size',          kind: 'number', label: 'Stone size (mm)',         min: 0.1, step: 0.1 },
      { key: 'stone_count',         kind: 'number', label: 'Stone count',             min: 1, step: 1 },
      { key: 'cap_half_angle_deg',  kind: 'number', label: 'Cap half-angle (°)',      min: 1, max: 89, step: 1 },
      { key: 'base_height',         kind: 'number', label: 'Base ring height (mm)',   min: 0, step: 0.1 },
    ],
  },
  {
    op: 'jewelry_patterned_bezel',
    label: 'Patterned Bezel',
    icon: Circle,
    defaults: { stone_diameter: 6.5, wall_thickness: 0.5, bezel_height: 3.0, bearing_ledge_height: 1.2, pattern: 'lotus', petal_count: 8 },
    fields: [
      { key: 'stone_diameter',       kind: 'number', label: 'Stone dia. (mm)',        min: 0.1, step: 0.1 },
      { key: 'wall_thickness',       kind: 'number', label: 'Wall thick. (mm)',       min: 0.1, step: 0.05 },
      { key: 'bezel_height',         kind: 'number', label: 'Bezel height (mm)',      min: 0.1, step: 0.1 },
      { key: 'bearing_ledge_height', kind: 'number', label: 'Bearing ledge ht. (mm)', min: 0.05, step: 0.05 },
      { key: 'pattern', kind: 'select', label: 'Pattern', options: [
        { value: 'lotus',   label: 'Lotus (floral petals)' },
        { value: 'compass', label: 'Compass (ray projections)' },
        { value: 'star',    label: 'Star (V-notch peaks)' },
        { value: 'plain',   label: 'Plain' },
      ] },
      { key: 'petal_count', kind: 'number', label: 'Petal / motif count', min: 3, step: 1,
        showWhen: (n) => n.pattern !== 'plain' },
    ],
  },
  {
    op: 'jewelry_trellis_prong',
    label: 'Trellis Prong',
    icon: Circle,
    defaults: { stone_diameter: 6.5, prong_count: 6, wire_gauge: 1.0, prong_height: 2.5, weave_style: 'x_cross', cross_height: 1.2 },
    caption: 'Trellis (cross-prong) basket — interwoven crossing prong wires around the stone.',
    fields: [
      { key: 'stone_diameter', kind: 'number', label: 'Stone dia. (mm)',    min: 0.1, step: 0.1 },
      { key: 'prong_count',    kind: 'number', label: 'Prong count (even)', min: 4, step: 2 },
      { key: 'wire_gauge',     kind: 'number', label: 'Wire gauge (mm)',    min: 0.1, step: 0.05 },
      { key: 'prong_height',   kind: 'number', label: 'Prong height (mm)',  min: 0.1, step: 0.1 },
      { key: 'weave_style', kind: 'select', label: 'Weave style', options: [
        { value: 'x_cross',  label: 'X-cross (plain weave)' },
        { value: 'diagonal', label: 'Diagonal (twill)' },
        { value: 'square',   label: 'Square (with cross-bars)' },
      ] },
      { key: 'cross_height', kind: 'number', label: 'Cross height (mm)', min: 0.01, step: 0.1 },
    ],
  },
  {
    op: 'jewelry_bar_channel_graduated',
    label: 'Grad. Bar Channel',
    icon: Layers,
    defaults: { stone_count: 5, largest_diameter: 3.0, smallest_diameter: 1.5, stone_spacing: 0.15, bar_width: 0.6, bar_height: 0.8, floor_thickness: 0.4 },
    caption: 'Graduated bar-channel row — stones taper from largest (centre) to smallest (ends) with bar pillars.',
    fields: [
      { key: 'stone_count',        kind: 'number', label: 'Stone count',             min: 1, step: 1 },
      { key: 'largest_diameter',   kind: 'number', label: 'Largest stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'smallest_diameter',  kind: 'number', label: 'Smallest stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'stone_spacing',      kind: 'number', label: 'Stone gap (mm)',          min: 0, step: 0.05 },
      { key: 'bar_width',          kind: 'number', label: 'Bar width (mm)',          min: 0.1, step: 0.05 },
      { key: 'bar_height',         kind: 'number', label: 'Bar height (mm)',         min: 0.1, step: 0.1 },
      { key: 'floor_thickness',    kind: 'number', label: 'Floor thickness (mm)',    min: 0.1, step: 0.05 },
    ],
  },

  // ── Gem seat types (channel_seat, bezel_seat, fishtail_seat, multi_stone_seat, pave_field_seat, cluster_halo_seat, gypsy_seat, baguette_channel_seat) ──

  {
    op: 'channel_seat',
    label: 'Channel Seat',
    icon: Layers,
    defaults: { cut: 'round_brilliant', diameter_mm: 2.5, n_stones: 7, pitch_mm: 2.8, girdle_clearance_mm: 0.05, crown_relief_mm: 0.3 },
    caption: 'Continuous bearing groove for a row of N stones. Use auto_cut_host_id to subtract from host.',
    fields: [
      { key: 'cut', kind: 'select', label: 'Cut', options: [
        { value: 'round_brilliant', label: 'Round brilliant' }, { value: 'princess', label: 'Princess' },
        { value: 'oval', label: 'Oval' }, { value: 'emerald', label: 'Emerald' },
        { value: 'marquise', label: 'Marquise' }, { value: 'pear', label: 'Pear' },
        { value: 'cushion', label: 'Cushion' }, { value: 'radiant', label: 'Radiant' },
        { value: 'asscher', label: 'Asscher' }, { value: 'trillion', label: 'Trillion' },
        { value: 'heart', label: 'Heart' }, { value: 'baguette', label: 'Baguette' },
        { value: 'briolette', label: 'Briolette' }, { value: 'old_european', label: 'Old European' },
        { value: 'old_mine', label: 'Old Mine' }, { value: 'rose_cut', label: 'Rose cut' },
        { value: 'single_cut', label: 'Single cut' }, { value: 'french_cut', label: 'French cut' },
        { value: 'half_moon', label: 'Half moon' }, { value: 'trapezoid', label: 'Trapezoid' },
        { value: 'kite', label: 'Kite' }, { value: 'bullet', label: 'Bullet' },
        { value: 'tapered_baguette', label: 'Tapered baguette' }, { value: 'lozenge', label: 'Lozenge' },
        { value: 'shield', label: 'Shield' }, { value: 'calf_head', label: 'Calf head' },
        { value: 'portuguese', label: 'Portuguese' }, { value: 'ceylon', label: 'Ceylon' },
        { value: 'flanders', label: 'Flanders' }, { value: 'square_emerald', label: 'Square emerald' },
      ] },
      { key: 'diameter_mm', kind: 'number', label: 'Stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'n_stones',    kind: 'number', label: 'Stone count',     min: 1, step: 1 },
      { key: 'pitch_mm',    kind: 'number', label: 'C-to-C pitch (mm)', min: 0.1, step: 0.05 },
      { key: 'girdle_clearance_mm', kind: 'number', label: 'Girdle clearance (mm)', min: 0, step: 0.01 },
      { key: 'crown_relief_mm',     kind: 'number', label: 'Crown relief (mm)',     min: 0, step: 0.05 },
      { key: 'auto_cut_host_id',    kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },
  {
    op: 'bezel_seat',
    label: 'Bezel Seat',
    icon: Circle,
    defaults: { cut: 'round_brilliant', diameter_mm: 6.5, bezel_wall_height_mm: 1.0, tapered: false, taper_angle_deg: 5, girdle_clearance_mm: 0.08, crown_relief_mm: 0.2 },
    caption: 'Inner bearing ledge for bezel / collet. Set tapered=true for collet-style tapered bore.',
    fields: [
      { key: 'cut', kind: 'select', label: 'Cut', options: [
        { value: 'round_brilliant', label: 'Round brilliant' }, { value: 'princess', label: 'Princess' },
        { value: 'oval', label: 'Oval' }, { value: 'emerald', label: 'Emerald' },
        { value: 'marquise', label: 'Marquise' }, { value: 'pear', label: 'Pear' },
        { value: 'cushion', label: 'Cushion' }, { value: 'radiant', label: 'Radiant' },
        { value: 'asscher', label: 'Asscher' }, { value: 'trillion', label: 'Trillion' },
        { value: 'heart', label: 'Heart' }, { value: 'baguette', label: 'Baguette' },
        { value: 'briolette', label: 'Briolette' }, { value: 'old_european', label: 'Old European' },
        { value: 'old_mine', label: 'Old Mine' }, { value: 'rose_cut', label: 'Rose cut' },
        { value: 'single_cut', label: 'Single cut' }, { value: 'french_cut', label: 'French cut' },
        { value: 'half_moon', label: 'Half moon' }, { value: 'trapezoid', label: 'Trapezoid' },
        { value: 'kite', label: 'Kite' }, { value: 'bullet', label: 'Bullet' },
        { value: 'tapered_baguette', label: 'Tapered baguette' }, { value: 'lozenge', label: 'Lozenge' },
        { value: 'shield', label: 'Shield' }, { value: 'calf_head', label: 'Calf head' },
        { value: 'portuguese', label: 'Portuguese' }, { value: 'ceylon', label: 'Ceylon' },
        { value: 'flanders', label: 'Flanders' }, { value: 'square_emerald', label: 'Square emerald' },
      ] },
      { key: 'diameter_mm',          kind: 'number',  label: 'Stone dia. (mm)',          min: 0.1, step: 0.1 },
      { key: 'bezel_wall_height_mm', kind: 'number',  label: 'Wall height above girdle (mm)', min: 0.1, step: 0.1 },
      { key: 'tapered',              kind: 'boolean', label: 'Tapered bore (collet)' },
      { key: 'taper_angle_deg',      kind: 'number',  label: 'Taper angle (°)', min: 0.1, max: 30, step: 0.5,
        showWhen: (n) => n.tapered },
      { key: 'girdle_clearance_mm',  kind: 'number',  label: 'Girdle clearance (mm)', min: 0, step: 0.01 },
      { key: 'crown_relief_mm',      kind: 'number',  label: 'Crown relief (mm)',     min: 0, step: 0.05 },
      { key: 'auto_cut_host_id',     kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },
  {
    op: 'fishtail_seat',
    label: 'Fishtail Seat',
    icon: Disc,
    defaults: { cut: 'round_brilliant', diameter_mm: 2.0, bright_cut_angle_deg: 45, bright_cut_depth_mm: 0.15, n_bright_facets: 4 },
    caption: 'Fishtail (bright-cut) accent seat with radial V-cut grooves. Common for pavé accent stones.',
    fields: [
      { key: 'cut', kind: 'select', label: 'Cut', options: [
        { value: 'round_brilliant', label: 'Round brilliant' }, { value: 'princess', label: 'Princess' },
        { value: 'oval', label: 'Oval' }, { value: 'marquise', label: 'Marquise' },
        { value: 'cushion', label: 'Cushion' },
      ] },
      { key: 'diameter_mm',           kind: 'number', label: 'Stone dia. (mm)',     min: 0.1, step: 0.1 },
      { key: 'bright_cut_angle_deg',  kind: 'number', label: 'Bright-cut angle (°)', min: 1, max: 89, step: 1 },
      { key: 'bright_cut_depth_mm',   kind: 'number', label: 'Bright-cut depth (mm)', min: 0.01, step: 0.01 },
      { key: 'n_bright_facets',       kind: 'number', label: 'Bright-cut facets',   min: 1, step: 1 },
      { key: 'auto_cut_host_id',      kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },

  // ── Ring ops v3–v4 ───────────────────────────────────────────────────────

  {
    op: 'eternity_band',
    label: 'Eternity Band',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', stone_diameter_mm: 2.0, coverage: 'full', setting_style: 'channel', band_width_mm: 3.0, thickness_mm: 1.2, stone_spacing_mm: 0.1 },
    fields: [
      { key: 'ring_size',  kind: 'number',  label: 'Ring size', min: 0 },
      { key: 'system',     kind: 'select',  label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'stone_diameter_mm', kind: 'number', label: 'Stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'coverage', kind: 'select', label: 'Coverage', options: [
        { value: 'full',          label: 'Full (360°)' },
        { value: 'half',          label: 'Half (180°)' },
        { value: 'three_quarter', label: 'Three-quarter (270°)' },
      ] },
      { key: 'setting_style', kind: 'select', label: 'Setting style', options: [
        { value: 'channel',      label: 'Channel' },
        { value: 'shared_prong', label: 'Shared prong' },
        { value: 'pave',         label: 'Pavé' },
      ] },
      { key: 'band_width_mm',     kind: 'number', label: 'Band width (mm)',    min: 0.1, step: 0.5 },
      { key: 'thickness_mm',      kind: 'number', label: 'Wall thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'stone_spacing_mm',  kind: 'number', label: 'Stone gap (mm)',      min: 0, step: 0.05 },
    ],
  },
  {
    op: 'signet_ring',
    label: 'Signet Ring',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', face_shape: 'oval', face_length_mm: 12.0, face_width_mm: 10.0, face_height_mm: 3.0, intaglio_depth_mm: 0, band_width_mm: 4.0, thickness_mm: 1.8, shoulder_style: 'plain' },
    fields: [
      { key: 'ring_size',     kind: 'number',  label: 'Ring size', min: 0 },
      { key: 'system',        kind: 'select',  label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'face_shape', kind: 'select', label: 'Face shape', options: [
        { value: 'flat',    label: 'Flat' },
        { value: 'oval',    label: 'Oval' },
        { value: 'cushion', label: 'Cushion' },
      ] },
      { key: 'face_length_mm',    kind: 'number', label: 'Seal length (mm)', min: 0.1, step: 0.5 },
      { key: 'face_width_mm',     kind: 'number', label: 'Seal width (mm)',  min: 0.1, step: 0.5 },
      { key: 'face_height_mm',    kind: 'number', label: 'Seal height (mm)', min: 0.1, step: 0.1 },
      { key: 'intaglio_depth_mm', kind: 'number', label: 'Intaglio depth (mm)', min: 0, step: 0.1 },
      { key: 'band_width_mm',     kind: 'number', label: 'Band width (mm)',  min: 0.1, step: 0.5 },
      { key: 'thickness_mm',      kind: 'number', label: 'Wall thick. (mm)', min: 0.1, step: 0.1 },
      { key: 'shoulder_style', kind: 'select', label: 'Shoulder style', options: [
        { value: 'plain',       label: 'Plain' }, { value: 'cathedral', label: 'Cathedral' },
        { value: 'split_shank', label: 'Split shank' }, { value: 'bypass', label: 'Bypass' },
      ] },
    ],
  },
  {
    op: 'stacking_band_set',
    label: 'Stacking Band Set',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', band_count: 3, band_width_mm: 2.0, thickness_mm: 1.4, profile: 'flat', nest_gap_mm: 0.1, include_wishbone: false },
    fields: [
      { key: 'ring_size',     kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system',        kind: 'select', label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'band_count',    kind: 'number', label: 'Band count', min: 1, max: 8, step: 1 },
      { key: 'band_width_mm', kind: 'number', label: 'Band width (mm)',    min: 0.1, step: 0.5 },
      { key: 'thickness_mm',  kind: 'number', label: 'Wall thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'profile', kind: 'select', label: 'Profile', options: [
        { value: 'flat',        label: 'Flat' }, { value: 'half_round',  label: 'Half round' },
        { value: 'knife_edge',  label: 'Knife edge' }, { value: 'euro', label: 'Euro' },
        { value: 'comfort_fit', label: 'Comfort fit' }, { value: 'd_shape', label: 'D-shape' },
        { value: 'cigar_band',  label: 'Cigar band' }, { value: 'concave', label: 'Concave' },
      ] },
      { key: 'nest_gap_mm',       kind: 'number',  label: 'Nest gap (mm)',    min: 0, step: 0.05 },
      { key: 'include_wishbone',  kind: 'boolean', label: 'Include wishbone/contour band' },
    ],
  },
  {
    op: 'contoured_band',
    label: 'Contoured Band',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', notch_depth_mm: 1.2, notch_width_mm: 3.0, match_radius_mm: 10.5, contour_style: 'curved', band_width_mm: 3.5, thickness_mm: 1.6, profile: 'flat', shoulder_style: 'plain' },
    caption: 'Shadow / contoured wedding band shaped to hug an engagement ring.',
    fields: [
      { key: 'ring_size',      kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system',         kind: 'select', label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'contour_style', kind: 'select', label: 'Contour style', options: [
        { value: 'curved',  label: 'Curved arc (shadow band)' },
        { value: 'notched', label: 'Notched (V/U centre)' },
      ] },
      { key: 'notch_depth_mm',   kind: 'number', label: 'Notch depth (mm)',  min: 0.01, step: 0.1 },
      { key: 'notch_width_mm',   kind: 'number', label: 'Notch width (mm)',  min: 0.01, step: 0.1 },
      { key: 'match_radius_mm',  kind: 'number', label: 'Match radius (mm)', min: 0.1, step: 0.5 },
      { key: 'band_width_mm',    kind: 'number', label: 'Band width (mm)',   min: 0.1, step: 0.5 },
      { key: 'thickness_mm',     kind: 'number', label: 'Wall thick. (mm)',  min: 0.1, step: 0.1 },
      { key: 'profile', kind: 'select', label: 'Profile', options: [
        { value: 'flat',        label: 'Flat' }, { value: 'half_round', label: 'Half round' },
        { value: 'comfort_fit', label: 'Comfort fit' }, { value: 'd_shape', label: 'D-shape' },
        { value: 'euro',        label: 'Euro' },
      ] },
      { key: 'shoulder_style', kind: 'select', label: 'Shoulder style', options: [
        { value: 'plain', label: 'Plain' }, { value: 'cathedral', label: 'Cathedral' },
        { value: 'split_shank', label: 'Split shank' }, { value: 'bypass', label: 'Bypass' },
      ] },
    ],
  },
  {
    op: 'solitaire_ring',
    label: 'Solitaire Ring',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', shank_profile: 'comfort_fit', shoulder_style: 'cathedral', band_width_mm: 3.0, thickness_mm: 1.6, head_height_mm: 5.0, center_stone_diameter_mm: 6.5, taper_ratio: 1.0 },
    fields: [
      { key: 'ring_size',    kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system',       kind: 'select', label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'shank_profile', kind: 'select', label: 'Shank profile', options: [
        { value: 'comfort_fit', label: 'Comfort fit' }, { value: 'd_shape', label: 'D-shape' },
        { value: 'flat', label: 'Flat' }, { value: 'half_round', label: 'Half round' },
        { value: 'knife_edge', label: 'Knife edge' }, { value: 'euro', label: 'Euro' },
        { value: 'tapered', label: 'Tapered' },
      ] },
      { key: 'shoulder_style', kind: 'select', label: 'Shoulder style', options: [
        { value: 'plain', label: 'Plain' }, { value: 'cathedral', label: 'Cathedral' },
        { value: 'split_shank', label: 'Split shank' }, { value: 'bypass', label: 'Bypass' },
      ] },
      { key: 'band_width_mm',            kind: 'number', label: 'Band width (mm)',         min: 0.1, step: 0.5 },
      { key: 'thickness_mm',             kind: 'number', label: 'Wall thick. (mm)',         min: 0.1, step: 0.1 },
      { key: 'head_height_mm',           kind: 'number', label: 'Head height (mm)',         min: 0.1, step: 0.5 },
      { key: 'center_stone_diameter_mm', kind: 'number', label: 'Centre stone dia. (mm)',   min: 0.1, step: 0.1 },
      { key: 'taper_ratio',              kind: 'number', label: 'Taper ratio (1=uniform)',  min: 0.1, max: 1.0, step: 0.05 },
    ],
  },
  {
    op: 'mens_band',
    label: "Men's Band",
    icon: Circle,
    defaults: { ring_size: 10, system: 'us', profile: 'comfort_fit', band_width_mm: 8.0, thickness_mm: 2.0, taper_ratio: 1.0, groove_depth_mm: 0, groove_width_mm: 1.5, milgrain_edges: false, surface_finish: 'polished' },
    fields: [
      { key: 'ring_size',   kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system',      kind: 'select', label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'profile', kind: 'select', label: 'Profile', options: [
        { value: 'comfort_fit', label: 'Comfort fit' }, { value: 'euro', label: 'Euro' },
        { value: 'd_shape', label: 'D-shape' }, { value: 'flat', label: 'Flat' },
        { value: 'cigar_band', label: 'Cigar band' }, { value: 'bombe', label: 'Bombé' },
        { value: 'concave', label: 'Concave' }, { value: 'square', label: 'Square' },
        { value: 'half_round', label: 'Half round' },
      ] },
      { key: 'band_width_mm', kind: 'number', label: 'Band width (mm)',    min: 0.1, step: 0.5 },
      { key: 'thickness_mm',  kind: 'number', label: 'Wall thick. (mm)',   min: 0.1, step: 0.1 },
      { key: 'taper_ratio',   kind: 'number', label: 'Taper ratio',        min: 0.1, max: 1.0, step: 0.05 },
      { key: 'groove_depth_mm', kind: 'number',  label: 'Groove depth (mm, 0=none)', min: 0, step: 0.1 },
      { key: 'groove_width_mm', kind: 'number',  label: 'Groove width (mm)',         min: 0.1, step: 0.1,
        showWhen: (n) => n.groove_depth_mm > 0 },
      { key: 'milgrain_edges', kind: 'boolean', label: 'Milgrain edges' },
      { key: 'surface_finish', kind: 'select', label: 'Surface finish', options: [
        { value: 'polished', label: 'Polished' }, { value: 'matte', label: 'Matte' },
        { value: 'hammered', label: 'Hammered' }, { value: 'satin', label: 'Satin' },
        { value: 'brushed',  label: 'Brushed' },
      ] },
    ],
  },
  {
    op: 'wedding_set',
    label: 'Wedding Set',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', eng_profile: 'comfort_fit', eng_shoulder_style: 'cathedral', eng_band_width_mm: 2.5, eng_thickness_mm: 1.6, band_profile: 'flat', band_width_mm: 3.0, band_thickness_mm: 1.6, contour_style: 'curved', notch_depth_mm: 1.2, notch_width_mm: 2.5 },
    caption: 'Engagement ring + matched contoured wedding band as a paired output node.',
    fields: [
      { key: 'ring_size', kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system',    kind: 'select', label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'eng_profile', kind: 'select', label: 'Eng. profile', options: [
        { value: 'comfort_fit', label: 'Comfort fit' }, { value: 'd_shape', label: 'D-shape' },
        { value: 'flat', label: 'Flat' }, { value: 'half_round', label: 'Half round' },
        { value: 'knife_edge', label: 'Knife edge' }, { value: 'euro', label: 'Euro' },
      ] },
      { key: 'eng_shoulder_style', kind: 'select', label: 'Eng. shoulder', options: [
        { value: 'plain', label: 'Plain' }, { value: 'cathedral', label: 'Cathedral' },
        { value: 'split_shank', label: 'Split shank' },
      ] },
      { key: 'eng_band_width_mm', kind: 'number', label: 'Eng. band width (mm)', min: 0.1, step: 0.5 },
      { key: 'eng_thickness_mm',  kind: 'number', label: 'Eng. thickness (mm)',  min: 0.1, step: 0.1 },
      { key: 'band_profile', kind: 'select', label: 'Band profile', options: [
        { value: 'flat', label: 'Flat' }, { value: 'half_round', label: 'Half round' },
        { value: 'comfort_fit', label: 'Comfort fit' },
      ] },
      { key: 'band_width_mm',     kind: 'number', label: 'Band width (mm)',    min: 0.1, step: 0.5 },
      { key: 'band_thickness_mm', kind: 'number', label: 'Band thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'contour_style', kind: 'select', label: 'Contour style', options: [
        { value: 'curved',  label: 'Curved arc' }, { value: 'notched', label: 'Notched' },
      ] },
      { key: 'notch_depth_mm', kind: 'number', label: 'Notch depth (mm)', min: 0.01, step: 0.1 },
      { key: 'notch_width_mm', kind: 'number', label: 'Notch width (mm)', min: 0.01, step: 0.1 },
    ],
  },
  {
    op: 'cocktail_ring',
    label: 'Cocktail Ring',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', shank_profile: 'tapered', shoulder_style: 'plain', band_width_mm: 4.0, thickness_mm: 1.8, taper_ratio: 0.7, mount_style: 'dome', mount_diameter_mm: 18.0, mount_height_mm: 8.0, stone_diameter_mm: 14.0 },
    fields: [
      { key: 'ring_size',  kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system',     kind: 'select', label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'shank_profile', kind: 'select', label: 'Shank profile', options: [
        { value: 'tapered', label: 'Tapered' }, { value: 'comfort_fit', label: 'Comfort fit' },
        { value: 'd_shape', label: 'D-shape' }, { value: 'flat', label: 'Flat' },
      ] },
      { key: 'shoulder_style', kind: 'select', label: 'Shoulder style', options: [
        { value: 'plain', label: 'Plain' }, { value: 'cathedral', label: 'Cathedral' },
        { value: 'split_shank', label: 'Split shank' },
      ] },
      { key: 'band_width_mm',      kind: 'number', label: 'Band width (mm)',    min: 0.1, step: 0.5 },
      { key: 'thickness_mm',       kind: 'number', label: 'Wall thick. (mm)',   min: 0.1, step: 0.1 },
      { key: 'taper_ratio',        kind: 'number', label: 'Taper ratio',        min: 0.1, max: 1.0, step: 0.05 },
      { key: 'mount_style', kind: 'select', label: 'Mount style', options: [
        { value: 'dome',    label: 'Dome' }, { value: 'cluster', label: 'Cluster' },
        { value: 'bezel',   label: 'Bezel' }, { value: 'prong',   label: 'Prong' },
      ] },
      { key: 'mount_diameter_mm',  kind: 'number', label: 'Mount dia. (mm)',    min: 0.1, step: 0.5 },
      { key: 'mount_height_mm',    kind: 'number', label: 'Mount height (mm)',  min: 0.1, step: 0.5 },
      { key: 'stone_diameter_mm',  kind: 'number', label: 'Stone dia. (mm)',    min: 0.1, step: 0.5 },
    ],
  },
  {
    op: 'bypass_ring',
    label: 'Bypass Ring',
    icon: Circle,
    defaults: { ring_size: 7, system: 'us', cross_style: 'crossover', profile: 'half_round', band_width_mm: 3.0, thickness_mm: 1.5, bypass_offset_mm: 4.0, overlap_deg: 20, stone_a_diameter_mm: 6.0, stone_b_diameter_mm: 6.0, mount_height_mm: 4.5 },
    caption: 'Two-element crossover or toi-et-moi ring with two stone mount attach-points.',
    fields: [
      { key: 'ring_size', kind: 'number', label: 'Ring size', min: 0 },
      { key: 'system',    kind: 'select', label: 'Size system', options: [
        { value: 'us', label: 'US' }, { value: 'uk', label: 'UK/AU' }, { value: 'eu', label: 'EU' }, { value: 'jp', label: 'JP' },
      ] },
      { key: 'cross_style', kind: 'select', label: 'Style', options: [
        { value: 'crossover',   label: 'Crossover' },
        { value: 'toi_et_moi',  label: 'Toi et moi' },
      ] },
      { key: 'profile', kind: 'select', label: 'Arm profile', options: [
        { value: 'half_round', label: 'Half round' }, { value: 'comfort_fit', label: 'Comfort fit' },
        { value: 'd_shape', label: 'D-shape' }, { value: 'flat', label: 'Flat' },
      ] },
      { key: 'band_width_mm',       kind: 'number', label: 'Arm width (mm)',     min: 0.1, step: 0.5 },
      { key: 'thickness_mm',        kind: 'number', label: 'Arm thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'bypass_offset_mm',    kind: 'number', label: 'Bypass offset (mm)', min: 0.1, step: 0.5 },
      { key: 'overlap_deg',         kind: 'number', label: 'Overlap (°)',         min: 0, max: 90, step: 1 },
      { key: 'stone_a_diameter_mm', kind: 'number', label: 'Stone A dia. (mm)',  min: 0.1, step: 0.1 },
      { key: 'stone_b_diameter_mm', kind: 'number', label: 'Stone B dia. (mm)',  min: 0.1, step: 0.1 },
      { key: 'mount_height_mm',     kind: 'number', label: 'Mount height (mm)', min: 0.1, step: 0.5 },
    ],
  },

  // ── Chain styles + composed pieces ─────────────────────────────────────

  {
    op: 'chain_assembly',
    label: 'Chain',
    icon: Layers,
    defaults: { style: 'cable', wire_gauge_mm: 1.0, total_length_mm: 457, open_ends: true, graduated: false },
    fields: [
      { key: 'style', kind: 'select', label: 'Chain style', options: [
        { value: 'cable',       label: 'Cable (alternating ovals)' },
        { value: 'curb',        label: 'Curb (flat twisted)' },
        { value: 'figaro',      label: 'Figaro (3+1 repeat)' },
        { value: 'rope',        label: 'Rope (helix)' },
        { value: 'box',         label: 'Box (square tube links)' },
        { value: 'snake',       label: 'Snake (scalloped)' },
        { value: 'byzantine',   label: 'Byzantine (4-link weave)' },
        { value: 'mariner',     label: 'Mariner / anchor' },
        { value: 'rolo',        label: 'Rolo / belcher' },
        { value: 'bismark',     label: 'Bismark (multi-row)' },
        { value: 'wheat',       label: 'Wheat / spiga' },
        { value: 'herringbone', label: 'Herringbone (flat woven)' },
        { value: 'omega',       label: 'Omega (plate spine)' },
        { value: 'popcorn',     label: 'Popcorn (spheroidal links)' },
        { value: 'ball',        label: 'Ball / bead chain' },
        { value: 'singapore',   label: 'Singapore (twisted curb)' },
      ] },
      { key: 'wire_gauge_mm',    kind: 'number', label: 'Wire gauge (mm)',       min: 0.1, step: 0.1 },
      { key: 'total_length_mm',  kind: 'number', label: 'Total length (mm)',     min: 1, step: 10 },
      { key: 'link_length_mm',   kind: 'number', label: 'Link length (mm)',      min: 0.1, step: 0.1 },
      { key: 'link_width_mm',    kind: 'number', label: 'Link width (mm)',       min: 0.1, step: 0.1 },
      { key: 'open_ends',        kind: 'boolean', label: 'Open end-links' },
      { key: 'graduated',        kind: 'boolean', label: 'Graduated (links scale from centre)' },
      { key: 'clasp_style', kind: 'select', label: 'Clasp style (optional)', options: [
        { value: '', label: 'None' },
        { value: 'lobster',      label: 'Lobster' },
        { value: 'spring_ring',  label: 'Spring ring' },
        { value: 'toggle',       label: 'Toggle' },
        { value: 'box_clasp',    label: 'Box clasp' },
      ] },
    ],
  },
  {
    op: 'tennis_bracelet',
    label: 'Tennis Bracelet',
    icon: Circle,
    defaults: { stone_diameter_mm: 3.0, stone_count: 20, wire_gauge_mm: 0.8, clasp_style: 'box_clasp' },
    fields: [
      { key: 'stone_diameter_mm', kind: 'number', label: 'Stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'stone_count',       kind: 'number', label: 'Stone count',     min: 1, step: 1 },
      { key: 'wire_gauge_mm',     kind: 'number', label: 'Wire gauge (mm)', min: 0.1, step: 0.05 },
      { key: 'clasp_style', kind: 'select', label: 'Clasp style', options: [
        { value: 'box_clasp',   label: 'Box clasp' },
        { value: 'lobster',     label: 'Lobster' },
        { value: 'toggle',      label: 'Toggle' },
        { value: 'spring_ring', label: 'Spring ring' },
      ] },
    ],
  },
  {
    op: 'station_necklace',
    label: 'Station Necklace',
    icon: Layers,
    defaults: { chain_style: 'cable', chain_wire_gauge_mm: 0.8, station_count: 7, station_diameter_mm: 5.0, total_length_mm: 457 },
    fields: [
      { key: 'chain_style', kind: 'select', label: 'Chain style', options: [
        { value: 'cable', label: 'Cable' }, { value: 'curb', label: 'Curb' },
        { value: 'box', label: 'Box' }, { value: 'singapore', label: 'Singapore' },
      ] },
      { key: 'chain_wire_gauge_mm', kind: 'number', label: 'Chain gauge (mm)', min: 0.1, step: 0.05 },
      { key: 'station_count',       kind: 'number', label: 'Station count',    min: 1, step: 1 },
      { key: 'station_diameter_mm', kind: 'number', label: 'Station dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'total_length_mm',     kind: 'number', label: 'Total length (mm)', min: 1, step: 10 },
    ],
  },
  {
    op: 'lariat',
    label: 'Lariat',
    icon: Layers,
    defaults: { chain_style: 'cable', wire_gauge_mm: 0.8, total_length_mm: 914, pendant_diameter_mm: 8.0 },
    fields: [
      { key: 'chain_style', kind: 'select', label: 'Chain style', options: [
        { value: 'cable', label: 'Cable' }, { value: 'rope', label: 'Rope' },
        { value: 'box', label: 'Box' }, { value: 'snake', label: 'Snake' },
      ] },
      { key: 'wire_gauge_mm',      kind: 'number', label: 'Wire gauge (mm)',       min: 0.1, step: 0.05 },
      { key: 'total_length_mm',    kind: 'number', label: 'Total length (mm)',     min: 1, step: 10 },
      { key: 'pendant_diameter_mm',kind: 'number', label: 'End pendant dia. (mm)', min: 0, step: 0.5 },
    ],
  },
  {
    op: 'charm_bracelet',
    label: 'Charm Bracelet',
    icon: Circle,
    defaults: { chain_style: 'cable', wire_gauge_mm: 1.2, total_length_mm: 190, charm_count: 5 },
    fields: [
      { key: 'chain_style', kind: 'select', label: 'Chain style', options: [
        { value: 'cable', label: 'Cable' }, { value: 'curb', label: 'Curb' },
        { value: 'rolo', label: 'Rolo' }, { value: 'box', label: 'Box' },
      ] },
      { key: 'wire_gauge_mm',  kind: 'number', label: 'Wire gauge (mm)',  min: 0.1, step: 0.1 },
      { key: 'total_length_mm',kind: 'number', label: 'Length (mm)',      min: 1, step: 5 },
      { key: 'charm_count',    kind: 'number', label: 'Charm attach slots', min: 0, step: 1 },
    ],
  },
  {
    op: 'multi_strand',
    label: 'Multi-Strand',
    icon: Layers,
    defaults: { strand_count: 3, chain_style: 'cable', wire_gauge_mm: 0.8, total_length_mm: 457, clasp_style: 'box_clasp' },
    fields: [
      { key: 'strand_count', kind: 'number', label: 'Strand count', min: 2, step: 1 },
      { key: 'chain_style', kind: 'select', label: 'Chain style', options: [
        { value: 'cable', label: 'Cable' }, { value: 'box', label: 'Box' },
        { value: 'rolo', label: 'Rolo' }, { value: 'snake', label: 'Snake' },
      ] },
      { key: 'wire_gauge_mm',   kind: 'number', label: 'Wire gauge (mm)',  min: 0.1, step: 0.05 },
      { key: 'total_length_mm', kind: 'number', label: 'Length (mm)',      min: 1, step: 10 },
      { key: 'clasp_style', kind: 'select', label: 'Clasp style', options: [
        { value: 'box_clasp', label: 'Box clasp' }, { value: 'toggle', label: 'Toggle' },
        { value: 'lobster', label: 'Lobster' },
      ] },
    ],
  },
  {
    op: 'extender_chain',
    label: 'Extender Chain',
    icon: Layers,
    defaults: { chain_style: 'cable', wire_gauge_mm: 0.6, length_mm: 50 },
    fields: [
      { key: 'chain_style', kind: 'select', label: 'Chain style', options: [
        { value: 'cable', label: 'Cable' }, { value: 'box', label: 'Box' }, { value: 'curb', label: 'Curb' },
      ] },
      { key: 'wire_gauge_mm', kind: 'number', label: 'Wire gauge (mm)', min: 0.1, step: 0.05 },
      { key: 'length_mm',     kind: 'number', label: 'Length (mm)',     min: 1, step: 5 },
    ],
  },

  // ── Findings ─────────────────────────────────────────────────────────────

  {
    op: 'finding',
    label: 'Finding',
    icon: Plus,
    defaults: { family: 'jump_ring', kind: 'round', wire_gauge_mm: 1.0, inner_diameter_mm: 5.0 },
    caption: 'Jewelry finding: jump ring, bail, ear finding, pin finding, end cap, or clasp.',
    fields: [
      { key: 'family', kind: 'select', label: 'Family', options: [
        { value: 'jump_ring',   label: 'Jump ring' },
        { value: 'bail',        label: 'Bail' },
        { value: 'ear_finding', label: 'Ear finding' },
        { value: 'pin_finding', label: 'Pin finding' },
        { value: 'end_cap',     label: 'End cap' },
        { value: 'clasp',       label: 'Clasp' },
      ] },
      { key: 'kind',           kind: 'text',   label: 'Kind (see jewelry_list_findings)' },
      { key: 'wire_gauge_mm',  kind: 'number', label: 'Wire gauge (mm)', min: 0.1, step: 0.05 },
      { key: 'inner_diameter_mm', kind: 'number', label: 'Inner dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'body_length_mm', kind: 'number', label: 'Body length (mm)', min: 0.1, step: 0.5 },
      { key: 'hook_length_mm', kind: 'number', label: 'Hook length (mm)', min: 0.1, step: 0.5 },
      { key: 'post_length_mm', kind: 'number', label: 'Post length (mm)', min: 0.1, step: 0.5 },
    ],
  },

  // ── Whole pieces: pendant, earrings, brooch, cufflink, bangle ────────────

  {
    op: 'pendant',
    label: 'Pendant',
    icon: Disc,
    defaults: { style: 'solitaire_drop', outline_shape: 'teardrop', width_mm: 12.0, height_mm: 18.0, thickness_mm: 1.5, bail_type: 'loop', bail_wire_gauge_mm: 1.0, centre_stone_diameter_mm: 6.0, halo_stone_count: 0 },
    fields: [
      { key: 'style', kind: 'select', label: 'Pendant style', options: [
        { value: 'solitaire_drop', label: 'Solitaire drop' },
        { value: 'halo',           label: 'Halo' },
        { value: 'cluster',        label: 'Cluster' },
        { value: 'locket',         label: 'Locket' },
        { value: 'charm',          label: 'Charm' },
      ] },
      { key: 'outline_shape', kind: 'select', label: 'Frame shape', options: [
        { value: 'round',     label: 'Round' },   { value: 'oval',    label: 'Oval' },
        { value: 'teardrop',  label: 'Teardrop' },{ value: 'square',  label: 'Square' },
        { value: 'rectangle', label: 'Rectangle' },{ value: 'hexagon', label: 'Hexagon' },
        { value: 'heart',     label: 'Heart' },   { value: 'free_form', label: 'Free form' },
      ] },
      { key: 'width_mm',     kind: 'number', label: 'Frame width (mm)',   min: 0.1, step: 0.5 },
      { key: 'height_mm',    kind: 'number', label: 'Frame height (mm)',  min: 0.1, step: 0.5 },
      { key: 'thickness_mm', kind: 'number', label: 'Thickness (mm)',     min: 0.1, step: 0.1 },
      { key: 'bail_type', kind: 'select', label: 'Bail type', options: [
        { value: 'loop',  label: 'Loop' }, { value: 'pinch', label: 'Pinch' },
        { value: 'snap',  label: 'Snap' }, { value: 'tube',  label: 'Tube' },
      ] },
      { key: 'bail_wire_gauge_mm',       kind: 'number', label: 'Bail gauge (mm)',        min: 0.1, step: 0.05 },
      { key: 'centre_stone_diameter_mm', kind: 'number', label: 'Centre stone dia. (mm)', min: 0, step: 0.1 },
      { key: 'halo_stone_diameter_mm',   kind: 'number', label: 'Halo stone dia. (mm)',   min: 0, step: 0.1 },
      { key: 'halo_stone_count',         kind: 'number', label: 'Halo stone count',       min: 0, step: 1 },
    ],
  },
  {
    op: 'earrings',
    label: 'Earrings',
    icon: Circle,
    defaults: { style: 'stud', face_diameter_mm: 8.0, face_thickness_mm: 1.2, wire_gauge_mm: 0.8, post_length_mm: 10.0, hoop_inner_diameter_mm: 16.0, drop_length_mm: 20.0, stone_diameter_mm: 5.0, stone_count: 1 },
    caption: 'Parametric matched earring pair (left + right). Styles: stud, drop, hoop, huggie, chandelier.',
    fields: [
      { key: 'style', kind: 'select', label: 'Style', options: [
        { value: 'stud',       label: 'Stud' },
        { value: 'drop',       label: 'Drop' },
        { value: 'hoop',       label: 'Hoop' },
        { value: 'huggie',     label: 'Huggie' },
        { value: 'chandelier', label: 'Chandelier' },
      ] },
      { key: 'face_diameter_mm',      kind: 'number', label: 'Face dia. (mm)',         min: 0.1, step: 0.5 },
      { key: 'face_thickness_mm',     kind: 'number', label: 'Face thickness (mm)',    min: 0.1, step: 0.1 },
      { key: 'wire_gauge_mm',         kind: 'number', label: 'Wire / post gauge (mm)', min: 0.1, step: 0.05 },
      { key: 'post_length_mm',        kind: 'number', label: 'Post length (mm)', min: 0.1, step: 0.5,
        showWhen: (n) => n.style === 'stud' || n.style === 'huggie' },
      { key: 'hoop_inner_diameter_mm',kind: 'number', label: 'Hoop inner dia. (mm)', min: 0.1, step: 1,
        showWhen: (n) => n.style === 'hoop' || n.style === 'huggie' },
      { key: 'drop_length_mm',        kind: 'number', label: 'Drop length (mm)', min: 0.1, step: 1,
        showWhen: (n) => n.style === 'drop' || n.style === 'chandelier' },
      { key: 'stone_diameter_mm', kind: 'number', label: 'Stone dia. (mm)', min: 0, step: 0.1 },
      { key: 'stone_count',       kind: 'number', label: 'Stone count',     min: 1, step: 1 },
    ],
  },
  {
    op: 'brooch',
    label: 'Brooch',
    icon: Disc,
    defaults: { shape: 'oval', width_mm: 30.0, height_mm: 20.0, thickness_mm: 2.0, stone_diameter_mm: 0, stone_count: 0 },
    fields: [
      { key: 'shape', kind: 'select', label: 'Frame shape', options: [
        { value: 'round',       label: 'Round' },
        { value: 'oval',        label: 'Oval' },
        { value: 'square',      label: 'Square' },
        { value: 'rectangular', label: 'Rectangular' },
        { value: 'freeform',    label: 'Freeform' },
        { value: 'floral',      label: 'Floral' },
        { value: 'geometric',   label: 'Geometric' },
      ] },
      { key: 'width_mm',           kind: 'number', label: 'Width (mm)',        min: 0.1, step: 1 },
      { key: 'height_mm',          kind: 'number', label: 'Height (mm)',       min: 0.1, step: 1 },
      { key: 'thickness_mm',       kind: 'number', label: 'Thickness (mm)',    min: 0.1, step: 0.1 },
      { key: 'stone_diameter_mm',  kind: 'number', label: 'Stone dia. (mm, 0=none)', min: 0, step: 0.1 },
      { key: 'stone_count',        kind: 'number', label: 'Stone count',       min: 0, step: 1 },
    ],
  },
  {
    op: 'cufflink',
    label: 'Cufflink',
    icon: Disc,
    defaults: { face_width_mm: 14.0, face_height_mm: 10.0, face_thickness_mm: 3.0, back_style: 'toggle', post_length_mm: 8.0 },
    fields: [
      { key: 'face_width_mm',    kind: 'number', label: 'Face width (mm)',    min: 0.1, step: 0.5 },
      { key: 'face_height_mm',   kind: 'number', label: 'Face height (mm)',   min: 0.1, step: 0.5 },
      { key: 'face_thickness_mm',kind: 'number', label: 'Face thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'back_style', kind: 'select', label: 'Back style', options: [
        { value: 'toggle',     label: 'Toggle' },
        { value: 't_bar',      label: 'T-bar' },
        { value: 'chain',      label: 'Chain' },
        { value: 'bullet',     label: 'Bullet' },
        { value: 'whale_back', label: 'Whale-back' },
      ] },
      { key: 'post_length_mm',   kind: 'number', label: 'Post length (mm)', min: 0.1, step: 0.5 },
      { key: 'stone_diameter_mm',kind: 'number', label: 'Stone dia. (mm, 0=none)', min: 0, step: 0.1 },
    ],
  },
  {
    op: 'bangle',
    label: 'Bangle',
    icon: Circle,
    defaults: { form: 'closed', wrist_size: 165, wrist_size_system: 'mm', cross_section: 'round', wire_gauge_mm: 3.0, band_width_mm: 5.0, thickness_mm: 2.0 },
    fields: [
      { key: 'form', kind: 'select', label: 'Form', options: [
        { value: 'closed',    label: 'Closed bangle' },
        { value: 'open_cuff', label: 'Open cuff' },
      ] },
      { key: 'wrist_size',         kind: 'number', label: 'Wrist size',      min: 0.1 },
      { key: 'wrist_size_system', kind: 'select', label: 'Size system', options: [
        { value: 'mm',     label: 'Circumference (mm)' },
        { value: 'inches', label: 'Circumference (in)' },
        { value: 'us',     label: 'US bangle size' },
      ] },
      { key: 'cross_section', kind: 'select', label: 'Cross-section', options: [
        { value: 'round',      label: 'Round' },
        { value: 'oval',       label: 'Oval' },
        { value: 'flat',       label: 'Flat' },
        { value: 'half_round', label: 'Half round' },
        { value: 'square',     label: 'Square' },
      ] },
      { key: 'wire_gauge_mm', kind: 'number', label: 'Wire gauge (mm)', min: 0.1, step: 0.1 },
      { key: 'band_width_mm', kind: 'number', label: 'Band width (mm)', min: 0.1, step: 0.5 },
      { key: 'thickness_mm',  kind: 'number', label: 'Thickness (mm)',  min: 0.1, step: 0.1 },
    ],
  },

  // ── Decorative ops ───────────────────────────────────────────────────────

  {
    op: 'decorative_apply',
    label: 'Decorative',
    icon: Waves,
    defaults: { feature: 'milgrain', target_ref: '', bead_diameter_mm: 0.6, pitch_mm: 0.7 },
    caption: 'Decorative surface / edge treatment. feature selects the treatment kind.',
    fields: [
      { key: 'feature', kind: 'select', label: 'Treatment', options: [
        { value: 'milgrain',        label: 'Milgrain (bead row)' },
        { value: 'beading',         label: 'Beading' },
        { value: 'filigree',        label: 'Filigree wire-work' },
        { value: 'twisted_wire',    label: 'Twisted wire' },
        { value: 'scrollwork',      label: 'Scrollwork' },
        { value: 'surface_texture', label: 'Surface texture' },
      ] },
      { key: 'target_ref',      kind: 'feature_picker', label: 'Target edge / face' },
      { key: 'bead_diameter_mm',kind: 'number', label: 'Bead / unit dia. (mm)', min: 0.1, step: 0.05 },
      { key: 'pitch_mm',        kind: 'number', label: 'Pitch / spacing (mm)',  min: 0.05, step: 0.05 },
      { key: 'offset_mm',       kind: 'number', label: 'Edge offset (mm)',      min: -5, max: 5, step: 0.05 },
    ],
  },

  // T-1 Sheet metal — folded flange primitive.
  // Unfold (T-2), flat-pattern (T-3), and bend table (T-4) are follow-ups.
  {
    op: 'sheet_metal_flange',
    label: 'Sheet Flange',
    icon: Layers,
    defaults: {
      base_width: 100,
      base_depth: 80,
      thickness: 1.5,
      edge_ref: 'top-front',
      flange_length: 25,
      bend_angle_deg: 90,
      bend_radius: 2,
      k_factor: 0.44,
    },
    caption: (
      'Folded sheet-metal flange: base plate + bent wall along a chosen top edge. ' +
      'k_factor (0 < k < 1) stores the neutral-axis offset for unfold (T-2, not yet shipped). ' +
      'Edge ref: top-front | top-back | top-left | top-right.'
    ),
    fields: [
      { key: 'base_width',      kind: 'number',  label: 'Base width (mm)',        min: 0.1, step: 1 },
      { key: 'base_depth',      kind: 'number',  label: 'Base depth (mm)',         min: 0.1, step: 1 },
      { key: 'thickness',       kind: 'number',  label: 'Sheet thickness (mm)',    min: 0.1, step: 0.1 },
      { key: 'edge_ref',        kind: 'select',  label: 'Fold edge', options: [
        { value: 'top-front',  label: 'Top front' },
        { value: 'top-back',   label: 'Top back' },
        { value: 'top-left',   label: 'Top left' },
        { value: 'top-right',  label: 'Top right' },
      ] },
      { key: 'flange_length',   kind: 'number',  label: 'Flange length (mm)',      min: 0.1, step: 1 },
      { key: 'bend_angle_deg',  kind: 'number',  label: 'Bend angle (°)',          min: 0.1, max: 180, step: 1 },
      { key: 'bend_radius',     kind: 'number',  label: 'Inside bend radius (mm)', min: 0,   step: 0.5 },
      { key: 'k_factor',        kind: 'number',  label: 'K-factor (0–1)',          min: 0.01, max: 0.99, step: 0.01 },
    ],
  },

  // ── GK-P45: SubD/mesh authoring ops ────────────────────────────────────────

  // subd_poke — centroid fan on a SubD cage face (GK-P20)
  {
    op: 'subd_poke',
    label: 'SubD Poke',
    icon: GitBranch,
    caption: 'Poke a SubD cage face: insert a centroid vertex and fan the n-gon into n triangles.',
    defaults: { target_id: '', face_id: 0 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'face_id',   kind: 'number',          label: 'Face index', min: 0, step: 1 },
    ],
  },

  // subd_extrude_along — extrude SubD face along polyline (GK-P21)
  {
    op: 'subd_extrude_along',
    label: 'SubD Extrude Along',
    icon: Layers,
    caption: 'Sweep a SubD cage face along a polyline spine. Side walls become quad faces.',
    defaults: { target_id: '', face_id: 0, curve_pts: [[0,0,0],[0,0,10]] },
    fields: [
      { key: 'target_id',  kind: 'feature_picker', label: 'SubD cage' },
      { key: 'face_id',    kind: 'number',          label: 'Face index', min: 0, step: 1 },
    ],
  },

  // sculpt_brush — sculpt-brush stroke (grab/smooth/inflate) (GK-P27)
  {
    op: 'sculpt_brush',
    label: 'Sculpt Brush',
    icon: Move,
    caption: 'Apply a sculpt-brush stroke to a SubD cage. Grab, smooth, or inflate vertices within the brush radius.',
    defaults: {
      target_id: '',
      center: [0, 0, 0],
      radius: 5.0,
      falloff: 2.0,
      strength: 0.5,
      mode: 'grab',
      direction: [0, 0, 1],
    },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'center[0]', kind: 'number', label: 'Brush centre X (mm)' },
      { key: 'center[1]', kind: 'number', label: 'Brush centre Y (mm)' },
      { key: 'center[2]', kind: 'number', label: 'Brush centre Z (mm)' },
      { key: 'radius',    kind: 'number', label: 'Radius (mm)', min: 0.001 },
      { key: 'falloff',   kind: 'number', label: 'Falloff exponent', min: 0.5, max: 8, step: 0.1 },
      { key: 'strength',  kind: 'number', label: 'Strength', min: 0, max: 1, step: 0.05 },
      { key: 'mode', kind: 'select', label: 'Mode', options: [
        { value: 'grab',    label: 'Grab (translate)' },
        { value: 'smooth',  label: 'Smooth (laplacian)' },
        { value: 'inflate', label: 'Inflate (along normal)' },
      ] },
      { key: 'direction[0]', kind: 'number', label: 'Grab dir X', showWhen: (n) => n.mode === 'grab' },
      { key: 'direction[1]', kind: 'number', label: 'Grab dir Y', showWhen: (n) => n.mode === 'grab' },
      { key: 'direction[2]', kind: 'number', label: 'Grab dir Z', showWhen: (n) => n.mode === 'grab' },
    ],
  },

  // multires_evaluate — MultiresStack evaluate + serialise (GK-P26)
  {
    op: 'multires_evaluate',
    label: 'MultiRes Evaluate',
    icon: Layers3,
    caption: 'Evaluate a MultiresStack at a subdivision level, applying per-vertex displacement maps for sculpting.',
    defaults: { target_id: '', level: 2, max_levels: 2, displacements: {} },
    fields: [
      { key: 'target_id',   kind: 'feature_picker', label: 'Base SubD cage' },
      { key: 'level',       kind: 'number', label: 'Evaluate at level', min: 0, max: 6, step: 1 },
      { key: 'max_levels',  kind: 'number', label: 'Max levels in stack', min: 1, max: 6, step: 1 },
    ],
  },

  // subd_deform_with_cage — deformation cage via mean-value coordinates (GK-P49)
  {
    op: 'subd_deform_with_cage',
    label: 'SubD Deform Cage',
    icon: GitBranch,
    caption: 'Control a high-resolution mesh by manipulating a low-resolution cage. Uses mean-value coordinates (Ju-Schaefer-Warren 2005) for smooth, partition-of-unity weighting.',
    defaults: {
      target_id: '',
      cage_deformed: [],
      n_cage_verts: 20,
      method: 'convex_hull',
    },
    fields: [
      { key: 'target_id',    kind: 'feature_picker', label: 'Detail SubD cage' },
      { key: 'n_cage_verts', kind: 'number', label: 'Cage vertices', min: 4, max: 200, step: 1 },
      { key: 'method', kind: 'select', label: 'Cage method', options: [
        { value: 'convex_hull',    label: 'Convex hull' },
        { value: 'simplification', label: 'Simplified hull' },
      ] },
    ],
  },

  // ── GK-P SubD extended ops (inset, bridge, loop-subdiv, limit, crease, CSG, etc.) ──

  // subd_inset_faces — inset selected faces by ratio (GK-P)
  {
    op: 'subd_inset_faces',
    label: 'SubD Inset Faces',
    icon: Cuboid,
    caption: 'Inset selected SubD cage faces by a ratio, creating an inner polygon ring per face. Useful for adding local control loops before sculpting.',
    defaults: { target_id: '', face_ids: [], inset_ratio: 0.25 },
    fields: [
      { key: 'target_id',   kind: 'feature_picker', label: 'SubD cage' },
      { key: 'inset_ratio', kind: 'number', label: 'Inset ratio (0–0.5)', min: 0.01, max: 0.5, step: 0.01 },
    ],
  },

  // subd_bridge_loops — bridge two edge loops into a connecting quad strip (GK-P)
  {
    op: 'subd_bridge_loops',
    label: 'SubD Bridge Loops',
    icon: GitMerge,
    caption: 'Bridge two open edge loops on a SubD cage with a quad-strip tube. Connects separate shells or fills a gap between loops.',
    defaults: { target_id: '', loop_a_edges: [], loop_b_edges: [], segments: 1 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'segments',  kind: 'number', label: 'Bridge segments', min: 1, max: 32, step: 1 },
    ],
  },

  // subd_loop_subdivision — apply n rounds of Catmull-Clark subdivision (GK-P)
  {
    op: 'subd_loop_subdivision',
    label: 'SubD Loop Subdivide',
    icon: Layers,
    caption: 'Apply n rounds of Catmull-Clark Loop subdivision to a SubD cage, increasing polygon density uniformly.',
    defaults: { target_id: '', levels: 1 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'levels',    kind: 'number', label: 'Subdivision levels', min: 1, max: 4, step: 1 },
    ],
  },

  // subd_compute_stam_limit_tangents — Stam 1998 exact limit tangents at extraordinary vertices (GK-P12)
  {
    op: 'subd_compute_stam_limit_tangents',
    label: 'SubD Limit Tangents',
    icon: Navigation,
    caption: 'Compute Stam 1998 exact limit-surface tangents (T1, T2) at extraordinary vertices. Inputs eigenvalues from the subdivision matrix; returns tangent-plane normal and G1 patch coefficients.',
    defaults: { target_id: '', vertex_ids: [] },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
    ],
  },

  // subd_convert_to_g1_patches — convert SubD cage to G1 Bezier patches (GK-P13)
  {
    op: 'subd_convert_to_g1_patches',
    label: 'SubD → G1 Patches',
    icon: Share2,
    caption: 'Convert a Catmull-Clark SubD cage to a set of bicubic Bézier patches that are G1-continuous at extraordinary vertices (Loop-Schaefer 2008 construction).',
    defaults: { target_id: '' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
    ],
  },

  // subd_apply_crease_decay — fractional crease sharpness decay per subdivision level (GK-P14)
  {
    op: 'subd_apply_crease_decay',
    label: 'SubD Crease Decay',
    icon: Layers,
    caption: 'Apply fractional crease-sharpness decay to SubD cage edges across subdivision levels. Partial crease values between 0 (smooth) and 1 (sharp corner) blend tangent directions for product-design fillets.',
    defaults: { target_id: '', edge_ids: [], sharpness: 1.0, decay_rate: 0.5 },
    fields: [
      { key: 'target_id',  kind: 'feature_picker', label: 'SubD cage' },
      { key: 'sharpness',  kind: 'number', label: 'Initial sharpness (0–3)', min: 0, max: 3, step: 0.1 },
      { key: 'decay_rate', kind: 'number', label: 'Decay rate per level', min: 0.1, max: 1.0, step: 0.05 },
    ],
  },

  // subd_collapse_edge — collapse a cage edge, merging its two vertices (GK-P)
  {
    op: 'subd_collapse_edge',
    label: 'SubD Collapse Edge',
    icon: Merge,
    caption: 'Collapse a SubD cage edge, merging its two endpoint vertices to their midpoint. Reduces polygon count locally and simplifies topology.',
    defaults: { target_id: '', edge_id: 0 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'edge_id',   kind: 'number', label: 'Edge index', min: 0, step: 1 },
    ],
  },

  // subd_sample_limit_normals — sample limit-surface normals on a regular UV grid (GK-P)
  {
    op: 'subd_sample_limit_normals',
    label: 'SubD Sample Limit Normals',
    icon: BrainCircuit,
    caption: 'Sample Stam exact limit-surface normals on each face at a regular (u,v) grid. Returns per-point normal vectors for rendering, G1 analysis, or normal-map baking.',
    defaults: { target_id: '', grid_u: 4, grid_v: 4 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'grid_u',    kind: 'number', label: 'Grid U samples', min: 2, max: 32, step: 1 },
      { key: 'grid_v',    kind: 'number', label: 'Grid V samples', min: 2, max: 32, step: 1 },
    ],
  },

  // subd_compute_cage_area — compute total cage polygon area (GK-P)
  {
    op: 'subd_compute_cage_area',
    label: 'SubD Cage Area',
    icon: Compass,
    caption: 'Compute the total surface area of a SubD cage by summing signed triangle areas for each polygon (fan-triangulation). Useful for material estimation before expensive limit-surface evaluation.',
    defaults: { target_id: '' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
    ],
  },

  // subd_evaluate_limit_normal — evaluate the exact limit-surface normal at one (u,v) (GK-P)
  {
    op: 'subd_evaluate_limit_normal',
    label: 'SubD Eval Limit Normal',
    icon: Navigation,
    caption: 'Evaluate the exact Stam limit-surface normal at a single (face_id, u, v) coordinate. Returns position + normal for high-precision shading or inspection.',
    defaults: { target_id: '', face_id: 0, u: 0.5, v: 0.5 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'face_id',   kind: 'number', label: 'Face index', min: 0, step: 1 },
      { key: 'u',         kind: 'number', label: 'U parameter (0–1)', min: 0, max: 1, step: 0.01 },
      { key: 'v',         kind: 'number', label: 'V parameter (0–1)', min: 0, max: 1, step: 0.01 },
    ],
  },

  // subd_extract_feature_curves — extract sharp-crease feature curves from cage (GK-P19)
  {
    op: 'subd_extract_feature_curves',
    label: 'SubD Extract Feature Curves',
    icon: Route,
    caption: 'Extract continuous polyline feature curves from sharp-crease edges of a SubD cage. Curves can be used as spine guides for sweep surfaces or sectioning.',
    defaults: { target_id: '', min_sharpness: 0.5 },
    fields: [
      { key: 'target_id',     kind: 'feature_picker', label: 'SubD cage' },
      { key: 'min_sharpness', kind: 'number', label: 'Minimum crease sharpness', min: 0, max: 3, step: 0.1 },
    ],
  },

  // subd_export_usdc — export limit surface as USDC binary crate (GK-P)
  {
    op: 'subd_export_usdc',
    label: 'SubD Export USDC',
    icon: PackageOpen,
    caption: 'Export a SubD cage limit surface as a minimal-conforming USDC binary crate (Pixar PXR-USDC 0.6.0). Targets HdStorm / Houdini / Maya USD workflows.',
    defaults: { target_id: '', levels: 2 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'levels',    kind: 'number', label: 'Subdivision levels for export', min: 0, max: 4, step: 1 },
    ],
  },

  // subd_geodesic_distance — heat-method geodesic distance from source vertices (GK-P49)
  {
    op: 'subd_geodesic_distance',
    label: 'SubD Geodesic Distance',
    icon: Compass,
    caption: 'Compute geodesic distances from one or more source vertices on a SubD cage using the heat method (Crane et al. 2013). Returns per-vertex distance field.',
    defaults: { target_id: '', source_vertex_ids: [0], t_scale: 1.0 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 't_scale',   kind: 'number', label: 'Heat diffusion time scale', min: 0.01, step: 0.1 },
    ],
  },

  // subd_csg_union — SubD cage boolean union (transversal case) (GK-P)
  {
    op: 'subd_csg_union',
    label: 'SubD CSG Union',
    icon: Ungroup,
    caption: 'Boolean union of two SubD cage meshes (transversal-contact case, Cohen-Or-Sheffer 2003). Detects intersection loop and stitches the two cage meshes.',
    defaults: { target_a_id: '', target_b_id: '' },
    fields: [
      { key: 'target_a_id', kind: 'feature_picker', label: 'SubD cage A' },
      { key: 'target_b_id', kind: 'feature_picker', label: 'SubD cage B' },
    ],
  },

  // subd_csg_difference — SubD cage boolean difference (GK-P)
  {
    op: 'subd_csg_difference',
    label: 'SubD CSG Difference',
    icon: Scissors,
    caption: 'Boolean difference (A minus B) of two SubD cage meshes (transversal case). Cuts cage B out of cage A.',
    defaults: { target_a_id: '', target_b_id: '' },
    fields: [
      { key: 'target_a_id', kind: 'feature_picker', label: 'SubD cage A (base)' },
      { key: 'target_b_id', kind: 'feature_picker', label: 'SubD cage B (cutter)' },
    ],
  },

  // subd_csg_intersection — SubD cage boolean intersection (GK-P)
  {
    op: 'subd_csg_intersection',
    label: 'SubD CSG Intersection',
    icon: Boxes,
    caption: 'Boolean intersection of two SubD cage meshes — keeps only the volume common to both. Transversal case (Cohen-Or-Sheffer 2003).',
    defaults: { target_a_id: '', target_b_id: '' },
    fields: [
      { key: 'target_a_id', kind: 'feature_picker', label: 'SubD cage A' },
      { key: 'target_b_id', kind: 'feature_picker', label: 'SubD cage B' },
    ],
  },

  // subd_project_primitive — project a SDF primitive onto cage surface (GK-P)
  {
    op: 'subd_project_primitive',
    label: 'SubD Project Primitive',
    icon: Wand2,
    caption: 'Project a SDF primitive (sphere / box / cylinder) onto the nearest-point surface of a SubD cage. Embeds the primitive silhouette as a crease loop.',
    defaults: { target_id: '', primitive_type: 'sphere', cx: 0, cy: 0, cz: 0, r: 5 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'primitive_type', kind: 'select', label: 'Primitive', options: [
        { value: 'sphere',   label: 'Sphere' },
        { value: 'box',      label: 'Box' },
        { value: 'cylinder', label: 'Cylinder' },
      ] },
      { key: 'cx', kind: 'number', label: 'Centre X (mm)' },
      { key: 'cy', kind: 'number', label: 'Centre Y (mm)' },
      { key: 'cz', kind: 'number', label: 'Centre Z (mm)' },
      { key: 'r',  kind: 'number', label: 'Radius / half-size (mm)', min: 0.001 },
    ],
  },

  // subd_symmetrize — enforce bilateral symmetry across a mirror plane (GK-P)
  {
    op: 'subd_symmetrize',
    label: 'SubD Symmetrize',
    icon: FlipHorizontal,
    caption: 'Enforce bilateral mirror symmetry on a SubD cage across a chosen plane (XY / YZ / XZ). Snaps vertices to the nearest symmetric position and welds mid-plane vertices.',
    defaults: { target_id: '', plane: 'YZ', tolerance: 0.001 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'SubD cage' },
      { key: 'plane', kind: 'select', label: 'Mirror plane', options: [
        { value: 'YZ', label: 'YZ (left↔right)' },
        { value: 'XZ', label: 'XZ (front↔back)' },
        { value: 'XY', label: 'XY (top↔bottom)' },
      ] },
      { key: 'tolerance', kind: 'number', label: 'Mid-plane weld tolerance (mm)', min: 0.0001, step: 0.0001 },
    ],
  },

  // ── GK-P46: mesh/implicit ops ───────────────────────────────────────────────

  // sdf_csg — SDF CSG + marching cubes (GK-P22)
  {
    op: 'sdf_csg',
    label: 'SDF CSG',
    icon: Combine,
    caption: 'Compose SDF primitives (sphere/box/cylinder) with CSG operators and extract a triangulated mesh via marching cubes.',
    defaults: {
      primitives: [{ type: 'sphere', id: 'a', cx: 0, cy: 0, cz: 0, r: 5 }],
      operations: [],
      bounds: [-10, -10, -10, 10, 10, 10],
      resolution: 32,
      isovalue: 0.0,
    },
    fields: [
      { key: 'resolution', kind: 'number', label: 'Resolution (per axis)', min: 4, max: 128, step: 4 },
      { key: 'isovalue',   kind: 'number', label: 'Iso-value', step: 0.01 },
    ],
  },

  // uv_unwrap — LSCM UV unwrap (GK-P24)
  {
    op: 'uv_unwrap',
    label: 'UV Unwrap',
    icon: LayoutGrid,
    caption: 'LSCM UV unwrap — computes a low-distortion (conformal) UV parametrization for a triangle mesh or SubD cage.',
    defaults: { target_id: '', fixed_pins: [] },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Mesh / SubD cage' },
    ],
  },

  // isotropic_remesh — Botsch-Kobbelt isotropic remesh (GK-P23)
  {
    op: 'isotropic_remesh',
    label: 'Isotropic Remesh',
    icon: Grid3x3,
    caption: 'Botsch-Kobbelt isotropic remesh: split, collapse, flip, and smooth toward a uniform target edge length.',
    defaults: { target_id: '', target_edge_length: 1.0, iterations: 5 },
    fields: [
      { key: 'target_id',          kind: 'feature_picker', label: 'Mesh / SubD cage' },
      { key: 'target_edge_length', kind: 'number',         label: 'Target edge length (mm)', min: 0.001 },
      { key: 'iterations',         kind: 'number',         label: 'Iterations', min: 1, max: 20, step: 1 },
    ],
  },

  // retopo_snap — snap retopo cage to reference mesh (GK-P25)
  {
    op: 'retopo_snap',
    label: 'Retopo Snap',
    icon: Crosshair,
    caption: 'Snap a retopo cage to the nearest-point surface of a reference mesh. Draw a coarse cage then snap it to conform.',
    defaults: { retopo_cage_id: '', source_mesh_id: '' },
    fields: [
      { key: 'retopo_cage_id',  kind: 'feature_picker', label: 'Retopo cage' },
      { key: 'source_mesh_id', kind: 'feature_picker', label: 'Reference mesh / scan' },
    ],
  },

  // ── GK-P47: surfacing additions ─────────────────────────────────────────────

  // isophote_analysis — read-only isophote continuity analyser (GK-P11)
  {
    op: 'isophote_analysis',
    label: 'Isophote Analysis',
    icon: Aperture,
    caption: (
      'Read-only isophote / environment-map continuity analysis. ' +
      'Detects G1 (tangent) discontinuities as isophote breaks. ' +
      'Does NOT append a geometry node — analysis only.'
    ),
    defaults: { target_id: '', uv_grid: [48, 48], sphere_map_res: 16, light_dir: [0, 0, 1] },
    fields: [
      { key: 'target_id',      kind: 'feature_picker', label: 'NURBS surface node' },
      { key: 'uv_grid[0]',     kind: 'number', label: 'UV grid U', min: 3, max: 200, step: 1 },
      { key: 'uv_grid[1]',     kind: 'number', label: 'UV grid V', min: 3, max: 200, step: 1 },
      { key: 'sphere_map_res', kind: 'number', label: 'Sphere-map bands', min: 2, max: 64, step: 1 },
      { key: 'light_dir[0]',   kind: 'number', label: 'Light dir X', step: 0.1 },
      { key: 'light_dir[1]',   kind: 'number', label: 'Light dir Y', step: 0.1 },
      { key: 'light_dir[2]',   kind: 'number', label: 'Light dir Z', step: 0.1 },
    ],
  },

  // ── GK-P48: construction verbs ──────────────────────────────────────────────

  // hem_sheet — 180° hem fold (GK-P17)
  {
    op: 'hem_sheet',
    label: 'Hem Sheet',
    icon: Layers,
    caption: '180° hem fold on a bent sheet-metal body (closed/open/teardrop). Stiffens edges and removes raw-cut burrs.',
    defaults: { target_id: '', style: 'closed', gap: 0, k_factor: 0.44 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Bent sheet body' },
      { key: 'style', kind: 'select', label: 'Hem style', options: [
        { value: 'closed',   label: 'Closed (flat, gap=0)' },
        { value: 'open',     label: 'Open (gap > 0)' },
        { value: 'teardrop', label: 'Teardrop' },
      ] },
      { key: 'gap',      kind: 'number', label: 'Gap (mm)', min: 0, step: 0.1, showWhen: (n) => n.style !== 'closed' },
      { key: 'radius',   kind: 'number', label: 'Hem radius (mm)', min: 0.001, step: 0.1 },
      { key: 'k_factor', kind: 'number', label: 'K-factor', min: 0.01, max: 0.99, step: 0.01 },
    ],
  },

  // jog_sheet — Z-offset jog (GK-P17)
  {
    op: 'jog_sheet',
    label: 'Jog Sheet',
    icon: SlidersHorizontal,
    caption: 'Z-offset jog (two opposing bends) on a sheet-metal body. Shifts one panel up/down while keeping both panels parallel.',
    defaults: { target_id: '', offset: 5.0, jog_angle_rad: 1.5708, radius: 1.0, k_factor: 0.44 },
    fields: [
      { key: 'target_id',     kind: 'feature_picker', label: 'Sheet-metal body' },
      { key: 'offset',        kind: 'number', label: 'Z offset (mm)' },
      { key: 'jog_angle_rad', kind: 'number', label: 'Jog angle (rad)', min: 0.01, max: 1.5708, step: 0.01 },
      { key: 'radius',        kind: 'number', label: 'Bend radius (mm)', min: 0.001, step: 0.1 },
      { key: 'k_factor',      kind: 'number', label: 'K-factor', min: 0.01, max: 0.99, step: 0.01 },
    ],
  },

  // multi_flange — sequence of bends (GK-P17)
  {
    op: 'multi_flange',
    label: 'Multi-Flange',
    icon: Repeat,
    caption: 'Apply a sequence of sheet-metal bends in one call. Each bend spec provides bend_line, angle_rad, and radius.',
    defaults: {
      target_id: '',
      bend_specs: [{ bend_line: 20, angle_rad: 1.5708, radius: 1.0, k_factor: 0.4 }],
    },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Sheet-metal body' },
    ],
  },

  // delete_face — remove a face (GK-P18)
  {
    op: 'delete_face',
    label: 'Delete Face',
    icon: Trash2,
    caption: 'Remove a face from a body and heal the result. For planar bodies this always produces a closed solid.',
    defaults: { target_id: '', face_id: 0, heal: true },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Body' },
      { key: 'face_id',   kind: 'number',          label: 'Face index', min: 0, step: 1 },
      { key: 'heal',      kind: 'boolean',          label: 'Attempt heal' },
    ],
  },

  // push_pull — push/pull non-planar face (GK-P18)
  // Note: the existing 'push_pull' op in 'modify' category is the basic version;
  // this one is tagged as a first-class feature node with target_id + face_id.
  {
    op: 'push_pull',
    label: 'Push/Pull Face',
    icon: Move,
    caption: 'Offset a face along its outward normal. Positive = outward (add material), negative = inward (remove). Supports non-planar faces (GK-P18).',
    defaults: { target_id: '', face_id: 0, distance: 5.0 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Body' },
      { key: 'face_id',   kind: 'number',          label: 'Face index', min: 0, step: 1 },
      { key: 'distance',  kind: 'number',           label: 'Distance (mm)', step: 0.5 },
    ],
  },

  // gusset_plate — weldment gusset (GK-P19)
  {
    op: 'gusset_plate',
    label: 'Gusset Plate',
    icon: GitBranch,
    caption: 'Insert a gusset-plate stiffener at a weldment joint vertex (triangle / rect / trapezoidal).',
    defaults: {
      target_id: '',
      vertex_pos: [0, 0, 0],
      thickness_mm: 6,
      width_mm: 100,
      height_mm: 100,
      shape: 'triangle',
      fillet_mm: 0,
      material: 'steel',
    },
    fields: [
      { key: 'target_id',    kind: 'feature_picker', label: 'Weldment frame' },
      { key: 'vertex_pos[0]', kind: 'number', label: 'Vertex X (mm)' },
      { key: 'vertex_pos[1]', kind: 'number', label: 'Vertex Y (mm)' },
      { key: 'vertex_pos[2]', kind: 'number', label: 'Vertex Z (mm)' },
      { key: 'thickness_mm', kind: 'number', label: 'Plate thickness (mm)', min: 0.1, step: 1 },
      { key: 'width_mm',     kind: 'number', label: 'Width (mm)', min: 0.1, step: 5 },
      { key: 'height_mm',    kind: 'number', label: 'Height (mm)', min: 0.1, step: 5 },
      { key: 'shape', kind: 'select', label: 'Shape', options: [
        { value: 'triangle',    label: 'Triangle (right-triangle)' },
        { value: 'rect',        label: 'Rectangle' },
        { value: 'trapezoidal', label: 'Trapezoidal' },
      ] },
      { key: 'fillet_mm', kind: 'number', label: 'Corner fillet (mm)', min: 0, step: 1 },
    ],
  },

  // cope_notch — weldment cope / notch end-treatment (GK-P19)
  {
    op: 'cope_notch',
    label: 'Cope / Notch',
    icon: Scissors,
    caption: 'Cope or notch end-treatment on a weldment member end. Cope = cut for passing member; notch = V/square corner cut.',
    defaults: {
      target_id: '',
      member_index: 0,
      end: 'start',
      cope_style: 'none',
      cope_depth_mm: 0,
      cope_width_mm: 0,
      notch_style: 'none',
      notch_depth_mm: 0,
      notch_width_mm: 0,
      notch_angle_deg: 45,
    },
    fields: [
      { key: 'target_id',    kind: 'feature_picker', label: 'Weldment frame' },
      { key: 'member_index', kind: 'number', label: 'Member index', min: 0, step: 1 },
      { key: 'end', kind: 'select', label: 'End', options: [
        { value: 'start', label: 'Start end' },
        { value: 'end',   label: 'End end' },
      ] },
      { key: 'cope_style', kind: 'select', label: 'Cope style', options: [
        { value: 'none',   label: 'None' },
        { value: 'square', label: 'Square' },
        { value: 'radius', label: 'Radius (radiused corner)' },
      ] },
      { key: 'cope_depth_mm',  kind: 'number', label: 'Cope depth (mm)', min: 0, step: 1, showWhen: (n) => n.cope_style !== 'none' },
      { key: 'cope_width_mm',  kind: 'number', label: 'Cope width (mm)', min: 0, step: 1, showWhen: (n) => n.cope_style !== 'none' },
      { key: 'cope_radius_mm', kind: 'number', label: 'Cope radius (mm)', min: 0, step: 0.5, showWhen: (n) => n.cope_style === 'radius' },
      { key: 'notch_style', kind: 'select', label: 'Notch style', options: [
        { value: 'none',   label: 'None' },
        { value: 'square', label: 'Square' },
        { value: 'angle',  label: 'V-notch' },
      ] },
      { key: 'notch_depth_mm', kind: 'number', label: 'Notch depth (mm)', min: 0, step: 1, showWhen: (n) => n.notch_style !== 'none' },
      { key: 'notch_width_mm', kind: 'number', label: 'Notch width (mm)', min: 0, step: 1, showWhen: (n) => n.notch_style !== 'none' },
      { key: 'notch_angle_deg', kind: 'number', label: 'V-notch angle (°)', min: 5, max: 170, step: 5, showWhen: (n) => n.notch_style === 'angle' },
    ],
  },

  // ── Construction helpers ──────────────────────────────────────────────────

  // rib — parametric reinforcement rib wall (feature_rib, kerf-imports)
  {
    op: 'rib',
    label: 'Rib',
    icon: AlignLeft,
    caption: (
      'Parametric reinforcement rib wall. Offsets a closed sketch profile and sweeps ' +
      'it into a solid wall for mold release or structural reinforcement. ' +
      'both_sides extrudes symmetrically; midplane centres on sketch plane.'
    ),
    defaults: {
      sketch_path: '',
      thickness_mm: 3.0,
      both_sides: false,
      midplane: false,
      draft_angle_deg: 0,
    },
    fields: [
      { key: 'sketch_path',     kind: 'sketch_picker', label: 'Closed profile sketch' },
      { key: 'thickness_mm',    kind: 'number', label: 'Wall thickness (mm)', min: 0.1, step: 0.5 },
      { key: 'both_sides',      kind: 'boolean', label: 'Both sides (symmetric extrude)' },
      { key: 'midplane',        kind: 'boolean', label: 'Midplane (centred on sketch)', showWhen: (n) => !n.both_sides },
      { key: 'draft_angle_deg', kind: 'number', label: 'Draft angle (°)', min: 0, max: 30, step: 0.5 },
    ],
  },

  // helix — parametric helix curve node (feature_helix, kerf-imports)
  {
    op: 'helix',
    label: 'Helix',
    icon: Activity,
    caption: (
      'Parametric helix / coil curve. Returns a polyline tracing a cylindrical or ' +
      'conical helix. Use as path_sketch for Sweep1 to produce springs, threads, ' +
      'or coiled tubing. direction: right (CCW, standard) / left (CW).'
    ),
    defaults: {
      pitch: 5.0,
      height: 30.0,
      radius: 10.0,
      direction: 'right',
      cone_angle: 0,
      segments: 64,
    },
    fields: [
      { key: 'pitch',       kind: 'number', label: 'Pitch — axial/turn (mm)', min: 0.01, step: 0.5 },
      { key: 'height',      kind: 'number', label: 'Total height (mm)',        min: 0.01, step: 1 },
      { key: 'radius',      kind: 'number', label: 'Base radius (mm)',          min: 0.01, step: 0.5 },
      { key: 'direction', kind: 'select', label: 'Handedness', options: [
        { value: 'right', label: 'Right-hand (CCW from above)' },
        { value: 'left',  label: 'Left-hand (CW from above)' },
      ] },
      { key: 'cone_angle',  kind: 'number', label: 'Cone half-angle (°, 0=cylindrical)', min: 0, max: 89, step: 0.5 },
      { key: 'segments',    kind: 'number', label: 'Segments / turn',  min: 8, max: 256, step: 8 },
    ],
  },

  // multi_transform — composited pattern (linear × polar × mirror) (kerf-imports)
  {
    op: 'multi_transform',
    label: 'Multi-Transform',
    icon: Repeat,
    caption: (
      'Compose up to 4 pattern operations (linear, polar, mirror) on one feature. ' +
      'Transforms are applied in order; the result is the Cartesian product of all instances. ' +
      'Useful for bolt circles combined with a mirror, or a polar array of a ribbed pattern.'
    ),
    defaults: {
      source_feature_id: '',
      transforms: [
        { kind: 'linear', direction: 'x', count: 3, spacing: 10 },
      ],
    },
    fields: [
      { key: 'source_feature_id', kind: 'feature_picker', label: 'Source feature' },
      // transforms is a complex nested list; LLM drives via JSON; inspector shows count only
    ],
  },

  // ── Surface quality analysis (read-only analysis nodes) ─────────────────

  // zebra_analysis — G0/G1/G2 stripe-break analysis (surfacing.py GK-38)
  {
    op: 'zebra_analysis',
    label: 'Zebra Analysis',
    icon: Eye,
    caption: (
      'Read-only zebra / reflection-line continuity analysis on the shared edge between ' +
      'two NURBS surfaces. Returns G0/G1/G2 stripe-break flags and reflection-line data. ' +
      'Use after blend_srf or blend_srf_g3 to verify join quality. Does NOT modify geometry.'
    ),
    defaults: {
      surface_a_ref: '',
      surface_b_ref: '',
      shared_edge_pts: [[0,0,0],[1,0,0]],
      num_samples: 32,
      stripe_width: 0.05,
    },
    fields: [
      { key: 'surface_a_ref',  kind: 'feature_picker', label: 'Surface A' },
      { key: 'surface_b_ref',  kind: 'feature_picker', label: 'Surface B' },
      { key: 'num_samples',    kind: 'number', label: 'Sample count', min: 4, max: 256, step: 4 },
      { key: 'stripe_width',   kind: 'number', label: 'Stripe width (fraction)', min: 0.01, max: 0.5, step: 0.01 },
    ],
  },

  // class_a_check — Class-A acceptance harness (surfacing.py GK-64)
  {
    op: 'class_a_check',
    label: 'Class-A Check',
    icon: Shield,
    caption: (
      'Class-A acceptance harness on the shared edge between two NURBS surfaces. ' +
      'Runs three passes: (1) curvature combs, (2) zebra/reflection-line, ' +
      '(3) G0/G1/G2/G3 gate. Optionally runs leading hot-spot detection on each surface. ' +
      'Read-only analysis node — does not modify geometry.'
    ),
    defaults: {
      surface_a_ref: '',
      surface_b_ref: '',
      shared_edge_pts: [[0,0,0],[1,0,0]],
      target_grade: 'G2',
      run_leading: false,
    },
    fields: [
      { key: 'surface_a_ref',  kind: 'feature_picker', label: 'Surface A' },
      { key: 'surface_b_ref',  kind: 'feature_picker', label: 'Surface B' },
      { key: 'target_grade', kind: 'select', label: 'Target grade', options: [
        { value: 'G0', label: 'G0 (positional)' },
        { value: 'G1', label: 'G1 (tangent)' },
        { value: 'G2', label: 'G2 (curvature)' },
        { value: 'G3', label: 'G3 (curvature-rate)' },
      ] },
      { key: 'run_leading', kind: 'boolean', label: 'Run leading hot-spot detection' },
    ],
  },

  // global_continuity_audit — walk every shared edge in a body (surfacing.py GK-138)
  {
    op: 'global_continuity_audit',
    label: 'Global Continuity Audit',
    icon: Shield,
    caption: (
      'Walk every shared edge in a feature body and classify each as G0/G1/G2/G3 or ' +
      'below_G0 for positional gaps. Returns a per-edge continuity report + summary ' +
      'count by grade. Read-only analysis node — does not modify geometry.'
    ),
    defaults: { target_id: '', tolerance: 1e-4 },
    fields: [
      { key: 'target_id',  kind: 'feature_picker', label: 'Surface body to audit' },
      { key: 'tolerance',  kind: 'number', label: 'Positional tolerance (mm)', min: 1e-9, step: 1e-4 },
    ],
  },

  // imprint_curve — project a 3D curve onto a face and record the resulting
  // boundary on the surface (surfacing.py / imprint.py imprint_curve_on_face).
  // UI: pick a source curve (.sketch path or feature id) + a target surface
  // (feature body ref + face name), click Run → calls imprint_curve_on_face,
  // displays the resulting boundary edge on the surface.
  // This is a Class-A G-5 toolpath imprint operation: the projected boundary
  // can be used as a trim curve for Class-A surface divisions.
  {
    op: 'imprint_curve',
    label: 'ImprintCurve',
    icon: Activity,
    caption: (
      'Project a 3D source curve onto a target NURBS face and imprint its ' +
      'boundary as a new edge on the surface. Used in Class-A toolpath wiring ' +
      'to create clean division edges for downstream trim and blend operations. ' +
      'Source curve: a .sketch path or a feature id whose output is a wire edge. ' +
      'After evaluation the imprinted boundary edge is returned as a new body.'
    ),
    defaults: {
      source_curve_ref: '',
      target_feature_ref: '',
      target_face_name: 'face-1',
      tolerance: 1e-3,
      extend_curve: false,
    },
    fields: [
      { key: 'source_curve_ref',  kind: 'sketch_picker',  label: 'Source curve (.sketch or feature id)' },
      { key: 'target_feature_ref',kind: 'feature_picker', label: 'Target surface / body' },
      { key: 'target_face_name',  kind: 'text',           label: 'Target face name (e.g. face-1)' },
      { key: 'tolerance',         kind: 'number',         label: 'Projection tolerance (mm)', min: 1e-9, step: 1e-4 },
      { key: 'extend_curve',      kind: 'boolean',        label: 'Extend curve to face boundary' },
    ],
  },

  // blend_srf_g3 — G3 degree-7 Bézier blend strip (surfacing.py GK-62)
  {
    op: 'blend_srf_g3',
    label: 'BlendSrf G3',
    icon: Waves,
    caption: (
      'G3 (curvature-rate-continuous) degree-7 Bézier blend strip between two NURBS surfaces. ' +
      'Highest analytic continuity class (G3); required for automotive Class-A and fine jewellery. ' +
      'Set trim_and_sew=true to also trim support surfaces and sew all three into a closed Body.'
    ),
    defaults: {
      target_id: '',
      edge1_id: -1,
      edge2_id: -1,
      blend_dist: 2.0,
      samples: 24,
      trim_and_sew: false,
    },
    fields: [
      { key: 'target_id',    kind: 'feature_picker', label: 'Host body' },
      { key: 'edge1_id',     kind: 'number', label: 'Edge 1 id', step: 1 },
      { key: 'edge2_id',     kind: 'number', label: 'Edge 2 id', step: 1 },
      { key: 'blend_dist',   kind: 'number', label: 'Blend distance (mm)', min: 0.001 },
      { key: 'samples',      kind: 'number', label: 'Seam sample count', min: 8, max: 128, step: 4 },
      { key: 'trim_and_sew', kind: 'boolean', label: 'Trim + sew into closed Body' },
    ],
  },

  // g3_chain_blend — multi-edge G3 chain blend (surfacing.py GK-P50)
  {
    op: 'g3_chain_blend',
    label: 'G3 Chain Blend',
    icon: Waves,
    caption: (
      'Multi-edge G3 chain blend: propagates a G3 continuity constraint along a ' +
      'chain of surface edges. Produces a single blend strip covering all edges in the chain.'
    ),
    defaults: {
      target_id: '',
      edge_chain: [],
      blend_dist: 2.0,
      samples: 24,
    },
    fields: [
      { key: 'target_id',  kind: 'feature_picker', label: 'Host body' },
      { key: 'blend_dist', kind: 'number', label: 'Blend distance (mm)', min: 0.001 },
      { key: 'samples',    kind: 'number', label: 'Sample count', min: 8, max: 256, step: 4 },
    ],
  },

  // fit_surface — fit NURBS surface to point cloud or mesh (surfacing.py)
  {
    op: 'fit_surface',
    label: 'Fit Surface',
    icon: Zap,
    caption: (
      'Fit a NURBS surface to a point cloud, mesh, or scan data. ' +
      'degree_u/v controls the polynomial degree; u_knots/v_knots controls knot count. ' +
      'Useful for reverse-engineering scanned geometry.'
    ),
    defaults: {
      source_ref: '',
      degree_u: 3,
      degree_v: 3,
      u_knots: 8,
      v_knots: 8,
      tolerance: 0.01,
    },
    fields: [
      { key: 'source_ref', kind: 'feature_picker', label: 'Source mesh / point cloud' },
      { key: 'degree_u',   kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',   kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'u_knots',    kind: 'number', label: 'U knot count', min: 2, max: 50, step: 1 },
      { key: 'v_knots',    kind: 'number', label: 'V knot count', min: 2, max: 50, step: 1 },
      { key: 'tolerance',  kind: 'number', label: 'Fit tolerance (mm)', min: 1e-6, step: 0.001 },
    ],
  },

  // ── Mechanical / solids (coverage sweep) ────────────────────────────────

  // feature_draft — taper-angle on faces for mold release
  {
    op: 'feature_draft',
    label: 'Draft',
    icon: SlidersHorizontal,
    caption: (
      'Apply a taper draft angle to a set of faces relative to a neutral plane. ' +
      'Standard operation for injection-molded parts to enable mold release. ' +
      'angle_deg is clamped to [-30, 30].'
    ),
    defaults: {
      face_ids: [],
      neutral_plane_face_id: 0,
      angle_deg: 3,
      pull_direction: 'outward',
    },
    fields: [
      { key: 'neutral_plane_face_id', kind: 'number', label: 'Neutral plane face id', min: 0, step: 1 },
      { key: 'angle_deg',     kind: 'number', label: 'Draft angle (°)', min: -30, max: 30, step: 0.5 },
      { key: 'pull_direction', kind: 'select', label: 'Pull direction', options: [
        { value: 'outward', label: 'Outward (widen from mold axis)' },
        { value: 'inward',  label: 'Inward (taper toward mold axis)' },
      ] },
    ],
  },

  // feature_mirror — mirror body about a world plane or face
  {
    op: 'feature_mirror',
    label: 'Mirror Body',
    icon: FlipHorizontal,
    caption: (
      'Mirror an existing feature or body about a world plane (XY/XZ/YZ) or a planar face id. ' +
      'When merge=true the mirrored copy is boolean-unioned with the original.'
    ),
    defaults: {
      source_feature_id: '',
      mirror_plane: 'XZ',
      merge: true,
    },
    fields: [
      { key: 'source_feature_id', kind: 'feature_picker', label: 'Source feature / body' },
      { key: 'mirror_plane', kind: 'select', label: 'Mirror plane (world)', options: [
        { value: 'XY', label: 'XY (horizontal)' },
        { value: 'XZ', label: 'XZ (front-back)' },
        { value: 'YZ', label: 'YZ (left-right)' },
      ] },
      { key: 'mirror_face_id', kind: 'number', label: 'Mirror face id (overrides plane)', min: 0, step: 1 },
      { key: 'merge', kind: 'boolean', label: 'Merge (union) with original' },
    ],
  },

  // feature_tapped_hole — parametric tapped hole from thread designation
  {
    op: 'feature_tapped_hole',
    label: 'Tapped Hole',
    icon: Drill,
    caption: (
      'Parametric tapped hole from standard thread designation (ISO metric or ASME UNC/UNF). ' +
      'Looks up tap-drill diameter from the thread-spec catalog and appends a hole-cut recipe. ' +
      'Accepted: "M6", "M6x0.75", "1/4-20 UNC", "#10-24 UNC".'
    ),
    defaults: {
      designation: 'M6',
      depth: 12,
      hole_type: 'through',
      target_id: '',
    },
    fields: [
      { key: 'designation', kind: 'text',   label: 'Thread designation (e.g. M6, 1/4-20 UNC)' },
      { key: 'depth',       kind: 'number', label: 'Hole depth (mm)', min: 0.001 },
      { key: 'hole_type',   kind: 'select', label: 'Hole type', options: [
        { value: 'through', label: 'Through' },
        { value: 'blind',   label: 'Blind' },
      ] },
      { key: 'thread_depth', kind: 'number', label: 'Thread depth (mm, blind only)', min: 0.001,
        showWhen: (n) => n.hole_type === 'blind' },
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
    ],
  },

  // feature_thread_external — external thread annotation / validation
  {
    op: 'feature_thread_external',
    label: 'External Thread',
    icon: Wrench,
    caption: (
      'Validate and annotate an external thread on a shaft. ' +
      'Checks shaft_dia matches the designation nominal major diameter within ±0.3 mm. ' +
      'Returns thread parameters for cosmetic annotation. ' +
      'Accepted: "M6", "M6x0.75", "1/4-20 UNC".'
    ),
    defaults: {
      shaft_dia: 6.0,
      designation: 'M6',
      length: 15,
    },
    fields: [
      { key: 'shaft_dia',   kind: 'number', label: 'Shaft outer dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'designation', kind: 'text',   label: 'Thread designation (e.g. M6, 1/4-20 UNC)' },
      { key: 'length',      kind: 'number', label: 'Thread length (mm)', min: 0.001 },
      { key: 'thread_class', kind: 'text',  label: 'Tolerance class (optional, e.g. 6g, 2A)' },
    ],
  },

  // feature_hole_pattern_from_sketch — hole pattern driven by sketch points
  {
    op: 'feature_hole_pattern_from_sketch',
    label: 'Hole Pattern (Sketch)',
    icon: LayoutGrid,
    caption: (
      'Cut a cylinder at every point entity in a sketch. ' +
      'Parametric: editing the sketch and re-evaluating updates all holes. ' +
      'Sketch must contain at least one type:"point" entity.'
    ),
    defaults: {
      sketch_path: '',
      target_id: '',
      diameter: 3,
      depth: 10,
      through: true,
    },
    fields: [
      { key: 'sketch_path', kind: 'sketch_picker', label: 'Points sketch' },
      { key: 'target_id',   kind: 'feature_picker', label: 'Target body' },
      { key: 'diameter',    kind: 'number', label: 'Hole diameter (mm)', min: 0.001 },
      { key: 'depth',       kind: 'number', label: 'Hole depth (mm)', min: 0.001 },
      { key: 'through',     kind: 'boolean', label: 'Through-hole' },
    ],
  },

  // sheet_metal_flat_pattern — flat-pattern DXF output from flange params
  {
    op: 'sheet_metal_flat_pattern',
    label: 'Flat Pattern',
    icon: Layers,
    caption: (
      'Produce a 2D flat-pattern DXF for a sheet-metal part. ' +
      'Uses the neutral-axis bend-allowance formula: BA = angle_rad × (radius + k_factor × thickness). ' +
      'Emits a DXF R12 with outline on layer "0" and bend lines on layer "BEND".'
    ),
    defaults: {
      base_length: 100,
      width: 80,
      flange_length: 25,
      bend_angle_deg: 90,
      bend_radius: 2,
      thickness: 1.5,
      k_factor: 0.44,
    },
    fields: [
      { key: 'base_length',    kind: 'number', label: 'Base length — bend dir (mm)', min: 0.1, step: 1 },
      { key: 'width',          kind: 'number', label: 'Width — perp. to bend (mm)',  min: 0.1, step: 1 },
      { key: 'flange_length',  kind: 'number', label: 'Flange length (mm)',           min: 0.1, step: 1 },
      { key: 'bend_angle_deg', kind: 'number', label: 'Bend angle (°)',               min: 0.1, max: 180, step: 1 },
      { key: 'bend_radius',    kind: 'number', label: 'Inside bend radius (mm)',      min: 0, step: 0.5 },
      { key: 'thickness',      kind: 'number', label: 'Sheet thickness (mm)',         min: 0.1, step: 0.1 },
      { key: 'k_factor',       kind: 'number', label: 'K-factor (0–1)',               min: 0.01, max: 0.99, step: 0.01 },
    ],
  },

  // sheet_metal_unfold — compute developed length of sheet-metal part
  {
    op: 'sheet_metal_unfold',
    label: 'Sheet Unfold',
    icon: Layers,
    caption: (
      'Compute the developed (flat) length of a sheet-metal part. ' +
      'Uses BA = angle_rad × (bend_radius + k_factor × thickness). ' +
      'Returns bend_allowance, developed_length, and bend_line positions.'
    ),
    defaults: {
      base_length: 100,
      flange_length: 25,
      bend_angle_deg: 90,
      bend_radius: 2,
      thickness: 1.5,
      k_factor: 0.44,
    },
    fields: [
      { key: 'base_length',    kind: 'number', label: 'Base length — bend dir (mm)', min: 0.1, step: 1 },
      { key: 'flange_length',  kind: 'number', label: 'Flange length (mm)',           min: 0.1, step: 1 },
      { key: 'bend_angle_deg', kind: 'number', label: 'Bend angle (°)',               min: 0.1, max: 180, step: 1 },
      { key: 'bend_radius',    kind: 'number', label: 'Inside bend radius (mm)',      min: 0, step: 0.5 },
      { key: 'thickness',      kind: 'number', label: 'Sheet thickness (mm)',         min: 0.1, step: 0.1 },
      { key: 'k_factor',       kind: 'number', label: 'K-factor (0–1)',               min: 0.01, max: 0.99, step: 0.01 },
    ],
  },

  // ── Gears ───────────────────────────────────────────────────────────────

  // gear_spur — external involute spur gear (ISO 21771)
  {
    op: 'gear_spur',
    label: 'Spur Gear',
    icon: GitBranch,
    caption: (
      'External involute spur gear profile (ISO 21771). ' +
      'Returns pitch/base/root/tip diameters, whole depth, circular pitch, ' +
      'tooth thickness, and a closed tooth-profile polyline.'
    ),
    defaults: {
      module: 2,
      teeth: 20,
      pressure_angle_deg: 20,
      face_width: 10,
      profile_shift: 0,
    },
    fields: [
      { key: 'module',             kind: 'number', label: 'Module m (mm)', min: 0.001, step: 0.25 },
      { key: 'teeth',              kind: 'number', label: 'Number of teeth z', min: 3, step: 1 },
      { key: 'pressure_angle_deg', kind: 'number', label: 'Pressure angle α (°)', min: 10, max: 30, step: 1 },
      { key: 'face_width',         kind: 'number', label: 'Face width b (mm)', min: 0.1, step: 1 },
      { key: 'profile_shift',      kind: 'number', label: 'Profile-shift x', step: 0.05 },
    ],
  },

  // gear_helical — helical gear (ISO 21771, transverse-plane analysis)
  {
    op: 'gear_helical',
    label: 'Helical Gear',
    icon: GitBranch,
    caption: (
      'Helical gear profile — extends spur with a helix angle β. ' +
      'Transverse module m_t = m_n / cos(β). ' +
      'Returns ISO 21771 helical gear data + transverse-plane tooth polyline.'
    ),
    defaults: {
      module: 2,
      teeth: 20,
      helix_angle_deg: 20,
      pressure_angle_deg: 20,
      face_width: 15,
    },
    fields: [
      { key: 'module',             kind: 'number', label: 'Normal module m_n (mm)', min: 0.001, step: 0.25 },
      { key: 'teeth',              kind: 'number', label: 'Number of teeth z', min: 3, step: 1 },
      { key: 'helix_angle_deg',    kind: 'number', label: 'Helix angle β (°)', min: 1, max: 89, step: 1 },
      { key: 'pressure_angle_deg', kind: 'number', label: 'Normal pressure angle α_n (°)', min: 10, max: 30, step: 1 },
      { key: 'face_width',         kind: 'number', label: 'Face width b (mm)', min: 0.1, step: 1 },
    ],
  },

  // gear_internal — internal (ring/annular) gear (ISO 21771)
  {
    op: 'gear_internal',
    label: 'Internal Gear',
    icon: GitBranch,
    caption: (
      'Internal (ring/annular) involute gear profile (ISO 21771 §4.3). ' +
      'Teeth point inward; tip dia < pitch dia, root dia > pitch dia. ' +
      'Returns ring-gear data + closed tooth polyline.'
    ),
    defaults: {
      module: 2,
      teeth: 40,
      pressure_angle_deg: 20,
      face_width: 10,
    },
    fields: [
      { key: 'module',             kind: 'number', label: 'Module m (mm)', min: 0.001, step: 0.25 },
      { key: 'teeth',              kind: 'number', label: 'Number of teeth z (ring)', min: 3, step: 1 },
      { key: 'pressure_angle_deg', kind: 'number', label: 'Pressure angle α (°)', min: 10, max: 30, step: 1 },
      { key: 'face_width',         kind: 'number', label: 'Face width b (mm)', min: 0.1, step: 1 },
      { key: 'profile_shift',      kind: 'number', label: 'Profile-shift x', step: 0.05 },
    ],
  },

  // gear_rack — linear involute rack (ISO 21771 §4.4)
  {
    op: 'gear_rack',
    label: 'Gear Rack',
    icon: GitBranch,
    caption: (
      'Linear involute rack profile (ISO 21771 §4.4). ' +
      'Flanks are straight lines at the pressure angle. ' +
      'Returns linear_pitch p = π·m, addendum/dedendum, and n-tooth outline polyline.'
    ),
    defaults: {
      module: 2,
      pressure_angle_deg: 20,
      n_teeth: 6,
      face_width: 10,
    },
    fields: [
      { key: 'module',             kind: 'number', label: 'Module m (mm)', min: 0.001, step: 0.25 },
      { key: 'pressure_angle_deg', kind: 'number', label: 'Pressure angle α (°)', min: 10, max: 30, step: 1 },
      { key: 'n_teeth',            kind: 'number', label: 'Number of rack teeth', min: 2, max: 50, step: 1 },
      { key: 'face_width',         kind: 'number', label: 'Face width b (mm)', min: 0.1, step: 1 },
    ],
  },

  // ── Jewelry gem-seat cuts (coverage sweep) ───────────────────────────────

  // jewelry_cut_baguette_channel_seat — rectangular bearing for step-cut stones
  {
    op: 'jewelry_cut_baguette_channel_seat',
    label: 'Baguette Channel Seat',
    icon: Layers,
    caption: (
      'Rectangular bearing groove for step-cut stones (baguette, emerald, princess). ' +
      'Prismatic rectangular slot — correct profile for rectangular/square girdles. ' +
      'Use auto_cut_host_id to subtract from the host solid.'
    ),
    defaults: {
      length_mm: 5.0,
      width_mm: 3.0,
      pavilion_depth_mm: 2.5,
      n_stones: 5,
      pitch_mm: 5.5,
    },
    fields: [
      { key: 'length_mm',         kind: 'number', label: 'Stone length (mm)',     min: 0.1, step: 0.1 },
      { key: 'width_mm',          kind: 'number', label: 'Stone width (mm)',      min: 0.1, step: 0.1 },
      { key: 'pavilion_depth_mm', kind: 'number', label: 'Pavilion depth (mm)',   min: 0.1, step: 0.1 },
      { key: 'n_stones',          kind: 'number', label: 'Stone count',           min: 1, step: 1 },
      { key: 'pitch_mm',          kind: 'number', label: 'C-to-C pitch (mm)',     min: 0.1, step: 0.1 },
      { key: 'wall_thickness_mm', kind: 'number', label: 'Min wall thickness (mm)', min: 0, step: 0.05 },
      { key: 'auto_cut_host_id',  kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },

  // jewelry_cut_cluster_halo_seat — center + ring of accent seats (halo/cluster)
  {
    op: 'jewelry_cut_cluster_halo_seat',
    label: 'Cluster Halo Seat',
    icon: Disc,
    caption: (
      'Center-stone seat surrounded by a ring of equally-spaced accent seats (halo/cluster setting). ' +
      'All accent seats are identical and placed at equal angular intervals. ' +
      'Use auto_cut_host_id to subtract all seats from the host.'
    ),
    defaults: {
      center_diameter_mm: 6.5,
      accent_diameter_mm: 1.3,
      n_accent: 18,
      halo_radius_mm: 4.5,
    },
    fields: [
      { key: 'center_diameter_mm',  kind: 'number', label: 'Center stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'accent_diameter_mm',  kind: 'number', label: 'Accent stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'n_accent',            kind: 'number', label: 'Accent stone count',     min: 3, step: 1 },
      { key: 'halo_radius_mm',      kind: 'number', label: 'Halo ring radius (mm)',  min: 0.1, step: 0.1 },
      { key: 'start_angle_deg',     kind: 'number', label: 'Start angle (°)',        step: 1 },
      { key: 'auto_cut_host_id',    kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },

  // jewelry_cut_gypsy_seat — flush/gypsy countersink seat
  {
    op: 'jewelry_cut_gypsy_seat',
    label: 'Gypsy Seat',
    icon: Disc,
    caption: (
      'Flush/gypsy countersink seat — stone girdle sits at the metal surface with no bearing cone overhang. ' +
      'Straight cylinder with shallow countersink for lower crown facets. ' +
      'Use for gypsy, burnish, and tube-set stones.'
    ),
    defaults: {
      diameter_mm: 4.0,
      countersink_angle_deg: 45,
      countersink_depth_mm: 0.3,
    },
    fields: [
      { key: 'diameter_mm',           kind: 'number', label: 'Stone diameter (mm)',         min: 0.1, step: 0.1 },
      { key: 'countersink_angle_deg', kind: 'number', label: 'Countersink angle (°)',       min: 1, max: 89, step: 1 },
      { key: 'countersink_depth_mm',  kind: 'number', label: 'Countersink depth (mm)',      min: 0.01, step: 0.05 },
      { key: 'girdle_clearance_mm',   kind: 'number', label: 'Girdle clearance (mm)',       min: 0, step: 0.01 },
      { key: 'auto_cut_host_id',      kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },

  // jewelry_cut_multi_stone_seat — graduated multi-stone shared seat
  {
    op: 'jewelry_cut_multi_stone_seat',
    label: 'Multi-Stone Seat',
    icon: Layers,
    caption: (
      'Graduated multi-stone shared seat: center stone flanked by smaller side stones (3-stone, 5-stone). ' +
      'n_side_stones must be even (symmetric) and ≥ 2.'
    ),
    defaults: {
      center_diameter_mm: 6.5,
      side_diameter_mm: 3.0,
      n_side_stones: 2,
      side_pitch_mm: 4.5,
    },
    fields: [
      { key: 'center_diameter_mm', kind: 'number', label: 'Center stone dia. (mm)', min: 0.1, step: 0.1 },
      { key: 'side_diameter_mm',   kind: 'number', label: 'Side stone dia. (mm)',   min: 0.1, step: 0.1 },
      { key: 'n_side_stones',      kind: 'number', label: 'Side stone count (even ≥ 2)', min: 2, step: 2 },
      { key: 'side_pitch_mm',      kind: 'number', label: 'Side C-to-C pitch (mm)', min: 0.1, step: 0.1 },
      { key: 'auto_cut_host_id',   kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },

  // jewelry_cut_pave_field_seat — grid/honeycomb of small bearing seats for pavé
  {
    op: 'jewelry_cut_pave_field_seat',
    label: 'Pavé Field Seat',
    icon: LayoutGrid,
    caption: (
      'Grid or honeycomb of small identical bearing seats for pavé-field settings. ' +
      'Use arrangement="honeycomb" for the classic offset-row pavé look.'
    ),
    defaults: {
      diameter_mm: 1.5,
      field_width_mm: 10.0,
      field_height_mm: 10.0,
      arrangement: 'honeycomb',
    },
    fields: [
      { key: 'diameter_mm',     kind: 'number', label: 'Stone dia. (mm)',      min: 0.1, step: 0.05 },
      { key: 'field_width_mm',  kind: 'number', label: 'Field width (mm)',     min: 0.1, step: 0.5 },
      { key: 'field_height_mm', kind: 'number', label: 'Field height (mm)',    min: 0.1, step: 0.5 },
      { key: 'arrangement', kind: 'select', label: 'Arrangement', options: [
        { value: 'honeycomb', label: 'Honeycomb (offset rows)' },
        { value: 'grid',      label: 'Grid (square)' },
      ] },
      { key: 'stone_gap_mm',    kind: 'number', label: 'Stone gap (mm)',       min: 0, step: 0.05 },
      { key: 'auto_cut_host_id', kind: 'feature_picker', label: 'Auto-cut host body' },
    ],
  },

  // ── BIM elements ─────────────────────────────────────────────────────────

  // bim_make_grid — structural grid (column + row axes)
  {
    op: 'bim_make_grid',
    label: 'BIM Grid',
    icon: Grid3x3,
    caption: (
      'Create a named structural grid from column axes (letters) and row axes (numbers). ' +
      'Supports regular (equal-bay) or irregular (custom spacing) modes.'
    ),
    defaults: {
      mode: 'regular',
      n_cols: 4,
      n_rows: 3,
      bay_width_m: 6.0,
      bay_depth_m: 6.0,
    },
    fields: [
      { key: 'mode', kind: 'select', label: 'Grid mode', options: [
        { value: 'regular', label: 'Regular (equal bays)' },
        { value: 'custom',  label: 'Custom (explicit coords)' },
      ] },
      { key: 'n_cols',       kind: 'number', label: 'Column axes', min: 2, step: 1, showWhen: (n) => n.mode === 'regular' },
      { key: 'n_rows',       kind: 'number', label: 'Row axes',    min: 2, step: 1, showWhen: (n) => n.mode === 'regular' },
      { key: 'bay_width_m',  kind: 'number', label: 'Bay width (m)',  min: 0.1, step: 0.5, showWhen: (n) => n.mode === 'regular' },
      { key: 'bay_depth_m',  kind: 'number', label: 'Bay depth (m)',  min: 0.1, step: 0.5, showWhen: (n) => n.mode === 'regular' },
    ],
  },

  // bim_make_framing — structural framing (columns + beams) on grid
  {
    op: 'bim_make_framing',
    label: 'BIM Framing',
    icon: LayoutGrid,
    caption: (
      'Create a structural framing layout (columns + beams) on a regular grid. ' +
      'Generates columns at every grid intersection and beams along grid lines at each storey.'
    ),
    defaults: {
      n_cols: 3,
      n_rows: 3,
      bay_width_m: 6.0,
      bay_depth_m: 6.0,
      column_section: 'UC203x203x46',
      beam_section: 'UB305x165x46',
    },
    fields: [
      { key: 'n_cols',          kind: 'number', label: 'Column-axis grid lines', min: 2, step: 1 },
      { key: 'n_rows',          kind: 'number', label: 'Row-axis grid lines',    min: 2, step: 1 },
      { key: 'bay_width_m',     kind: 'number', label: 'Bay width (m)',          min: 0.1, step: 0.5 },
      { key: 'bay_depth_m',     kind: 'number', label: 'Bay depth (m)',          min: 0.1, step: 0.5 },
      { key: 'column_section',  kind: 'text',   label: 'Column section (e.g. UC203x203x46)' },
      { key: 'beam_section',    kind: 'text',   label: 'Beam section (e.g. UB305x165x46)' },
    ],
  },

  // bim_make_wall — compound-layered wall instance
  {
    op: 'bim_make_wall',
    label: 'BIM Wall',
    icon: Box,
    caption: (
      'Create a compound-layered wall instance. ' +
      'Supply a preset_name for a pre-defined type or define custom layers. ' +
      'Geometry: start/end [x,y] in metres + height in metres.'
    ),
    defaults: {
      height_m: 3.0,
      preset_name: 'Ext - Single Brick 230',
    },
    fields: [
      { key: 'height_m',    kind: 'number', label: 'Wall height (m)',  min: 0.01, step: 0.1 },
      { key: 'preset_name', kind: 'text',   label: 'Wall preset (e.g. "Ext - Single Brick 230")' },
    ],
  },

  // bim_make_slab — floor or roof slab from boundary polygon
  {
    op: 'bim_make_slab',
    label: 'BIM Slab',
    icon: Layers,
    caption: (
      'Create a floor or roof slab from a boundary polygon. ' +
      'Supply a preset_name or define custom layers. ' +
      'Boundary: list of [x, y] vertices in metres (min 3 points).'
    ),
    defaults: {
      preset_name: 'RC Flat Slab 200',
      slab_function: 'floor',
    },
    fields: [
      { key: 'preset_name',    kind: 'text',   label: 'Slab preset (e.g. "RC Flat Slab 200")' },
      { key: 'slab_function',  kind: 'select', label: 'Slab function', options: [
        { value: 'floor',      label: 'Floor' },
        { value: 'roof',       label: 'Roof' },
        { value: 'foundation', label: 'Foundation' },
      ] },
    ],
  },

  // ── NURBS curve / surface analysis + editing tools ──────────────────────

  // nurbs_degree_raise — Cohen-Lyche-Schumaker 1985 degree elevation
  {
    op: 'nurbs_degree_raise',
    label: 'Degree Raise',
    icon: TrendingUp,
    category: 'nurbs',
    caption: (
      'Raise the degree of a NURBS curve or surface (Cohen-Lyche-Schumaker 1985). ' +
      'Exact — evaluated geometry is preserved to floating-point precision. ' +
      'Supply is_surface=true for surfaces (provides degree_u/v, knots_u/v).'
    ),
    defaults: {
      is_surface: false,
      degree: 3,
      target_degree: 4,
      control_points: [],
      knots: [],
    },
    fields: [
      { key: 'is_surface',    kind: 'boolean', label: 'Surface mode (vs curve)' },
      { key: 'degree',        kind: 'number',  label: 'Current degree (curve)', min: 1, max: 9, step: 1 },
      { key: 'target_degree', kind: 'number',  label: 'Target degree (curve)', min: 2, max: 10, step: 1 },
      { key: 'degree_u',      kind: 'number',  label: 'Current degree U (srf)', min: 1, max: 9, step: 1 },
      { key: 'degree_v',      kind: 'number',  label: 'Current degree V (srf)', min: 1, max: 9, step: 1 },
      { key: 'target_degree_u', kind: 'number', label: 'Target degree U (srf)', min: 2, max: 10, step: 1 },
      { key: 'target_degree_v', kind: 'number', label: 'Target degree V (srf)', min: 2, max: 10, step: 1 },
    ],
  },

  // nurbs_degree_lower — least-squares degree reduction
  {
    op: 'nurbs_degree_lower',
    label: 'Degree Lower',
    icon: ArrowUpDown,
    category: 'nurbs',
    caption: (
      'Lower the degree of a NURBS curve (Cohen-Lyche-Schumaker 1985 least-squares). ' +
      'Approximate — a tolerance parameter controls maximum deviation. ' +
      'Use to reduce control-point count while preserving shape within tolerance.'
    ),
    defaults: {
      degree: 4,
      target_degree: 3,
      control_points: [],
      knots: [],
      tolerance: 1e-4,
    },
    fields: [
      { key: 'degree',        kind: 'number', label: 'Current degree', min: 2, max: 10, step: 1 },
      { key: 'target_degree', kind: 'number', label: 'Target degree',  min: 1, max: 9,  step: 1 },
      { key: 'tolerance',     kind: 'number', label: 'Max deviation tolerance (mm)', min: 1e-9, step: 1e-5 },
    ],
  },

  // nurbs_surface_offset — Tiller-Hanson offset surface
  {
    op: 'nurbs_surface_offset',
    label: 'Surface Offset',
    icon: Maximize2,
    category: 'nurbs',
    caption: (
      'Offset a NURBS surface by a signed distance (positive = along normal). ' +
      'Uses the Tiller-Hanson control-point displacement method. ' +
      'For large distances with high-curvature surfaces use nurbs_surface_offset_robust.'
    ),
    defaults: {
      distance: 1.0,
      num_u: 4,
      num_v: 4,
      degree_u: 3,
      degree_v: 3,
      control_points: [],
      knots_u: [],
      knots_v: [],
    },
    fields: [
      { key: 'distance',  kind: 'number', label: 'Offset distance (mm)', step: 0.1 },
      { key: 'degree_u',  kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',  kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'num_u',     kind: 'number', label: 'CP count U', min: 2, max: 100, step: 1 },
      { key: 'num_v',     kind: 'number', label: 'CP count V', min: 2, max: 100, step: 1 },
    ],
  },

  // nurbs_surface_offset_robust — far-offset with Maekawa 1999 robustness
  {
    op: 'nurbs_surface_offset_robust',
    label: 'Surface Offset (Robust)',
    icon: Maximize2,
    category: 'nurbs',
    caption: (
      'Far-distance robust NURBS surface offset (Maekawa 1999). ' +
      'Handles self-intersection trimming and high-curvature regions that the ' +
      'standard offset fails on. Slower but more reliable for large offsets.'
    ),
    defaults: {
      distance: 2.0,
      degree_u: 3,
      degree_v: 3,
      num_u: 4,
      num_v: 4,
      control_points: [],
      knots_u: [],
      knots_v: [],
    },
    fields: [
      { key: 'distance',    kind: 'number', label: 'Offset distance (mm)', step: 0.5 },
      { key: 'degree_u',    kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',    kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'num_u',       kind: 'number', label: 'CP count U', min: 2, step: 1 },
      { key: 'num_v',       kind: 'number', label: 'CP count V', min: 2, step: 1 },
    ],
  },

  // nurbs_project_curve_to_surface — Newton-Raphson UV-trace projection
  {
    op: 'nurbs_project_curve_to_surface',
    label: 'Project Curve to Surface',
    icon: Route,
    category: 'nurbs',
    caption: (
      'Project a 3D NURBS curve onto a NURBS surface, tracing the closest-point ' +
      'UV locus via Newton-Raphson (Piegl-Tiller §6.1). ' +
      'Returns the projected curve as a degree-3 NURBS in UV parameter space.'
    ),
    defaults: {
      tol: 1e-4,
      samples: 20,
    },
    fields: [
      { key: 'tol',     kind: 'number', label: 'Projection tolerance (mm)', min: 1e-9, step: 1e-4 },
      { key: 'samples', kind: 'number', label: 'Seed sample count', min: 4, max: 200, step: 4 },
    ],
  },

  // nurbs_extract_iso_u / nurbs_extract_iso_v — iso-curve extraction
  {
    op: 'nurbs_extract_iso_u',
    label: 'Extract Iso-U Curve',
    icon: Spline,
    category: 'nurbs',
    caption: (
      'Extract the u-iso-curve C(t) = S(u₀, t) from a NURBS surface as a full ' +
      'parametric NurbsCurve (Piegl-Tiller §5.3 knot-insertion algorithm). ' +
      'The extracted curve has degree = surface degree_v and the v knot vector.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      num_u: 4,
      num_v: 4,
      u: 0.5,
      control_points: [],
      knots_u: [],
      knots_v: [],
    },
    fields: [
      { key: 'degree_u', kind: 'number', label: 'Surface degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v', kind: 'number', label: 'Surface degree V', min: 1, max: 9, step: 1 },
      { key: 'num_u',    kind: 'number', label: 'CP count U', min: 2, step: 1 },
      { key: 'num_v',    kind: 'number', label: 'CP count V', min: 2, step: 1 },
      { key: 'u',        kind: 'number', label: 'u parameter value', min: 0, max: 1, step: 0.05 },
    ],
  },

  {
    op: 'nurbs_extract_iso_v',
    label: 'Extract Iso-V Curve',
    icon: Spline,
    category: 'nurbs',
    caption: (
      'Extract the v-iso-curve C(t) = S(t, v₀) from a NURBS surface as a full ' +
      'parametric NurbsCurve (Piegl-Tiller §5.3 knot-insertion algorithm). ' +
      'The extracted curve has degree = surface degree_u and the u knot vector.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      num_u: 4,
      num_v: 4,
      v: 0.5,
      control_points: [],
      knots_u: [],
      knots_v: [],
    },
    fields: [
      { key: 'degree_u', kind: 'number', label: 'Surface degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v', kind: 'number', label: 'Surface degree V', min: 1, max: 9, step: 1 },
      { key: 'num_u',    kind: 'number', label: 'CP count U', min: 2, step: 1 },
      { key: 'num_v',    kind: 'number', label: 'CP count V', min: 2, step: 1 },
      { key: 'v',        kind: 'number', label: 'v parameter value', min: 0, max: 1, step: 0.05 },
    ],
  },

  // nurbs_split_curve — split a curve at one or more parameter values
  {
    op: 'nurbs_split_curve',
    label: 'Split Curve',
    icon: SplitSquareHorizontal,
    category: 'nurbs',
    caption: (
      'Split a NURBS curve into two or more segments at given parameter values ' +
      '(Piegl-Tiller knot insertion). Returns a list of NurbsCurve segments. ' +
      'The split preserves exact geometry (no approximation).'
    ),
    defaults: {
      degree: 3,
      t_values: [0.5],
      control_points: [],
      knots: [],
    },
    fields: [
      { key: 'degree',   kind: 'number', label: 'Curve degree', min: 1, max: 9, step: 1 },
    ],
  },

  // nurbs_split_surface — split a surface at u or v parameter
  {
    op: 'nurbs_split_surface',
    label: 'Split Surface',
    icon: SplitSquareHorizontal,
    category: 'nurbs',
    caption: (
      'Split a NURBS surface at a given u or v parameter value. ' +
      'Returns two NurbsSurface halves. Exact — knot insertion preserves geometry. ' +
      'direction: "u" splits along iso-v; "v" splits along iso-u.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      num_u: 4,
      num_v: 4,
      direction: 'u',
      t: 0.5,
      control_points: [],
      knots_u: [],
      knots_v: [],
    },
    fields: [
      { key: 'degree_u',  kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',  kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'num_u',     kind: 'number', label: 'CP count U', min: 2, step: 1 },
      { key: 'num_v',     kind: 'number', label: 'CP count V', min: 2, step: 1 },
      { key: 'direction', kind: 'select', label: 'Split direction', options: [
        { value: 'u', label: 'U (split at constant u)' },
        { value: 'v', label: 'V (split at constant v)' },
      ] },
      { key: 't', kind: 'number', label: 'Split parameter', min: 0.001, max: 0.999, step: 0.05 },
    ],
  },

  // nurbs_find_curve_inflections — Sturm-sequence / bisection inflection finder
  {
    op: 'nurbs_find_curve_inflections',
    label: 'Curve Inflections',
    icon: Workflow,
    category: 'nurbs',
    caption: (
      'Locate inflection points (κ = 0) on a planar NURBS curve via Sturm-sequence ' +
      'sign-change counting + bisection root finding. ' +
      'Returns parameter values and XYZ coordinates of all inflections.'
    ),
    defaults: {
      degree: 3,
      control_points: [],
      knots: [],
      samples: 64,
    },
    fields: [
      { key: 'degree',  kind: 'number', label: 'Curve degree', min: 1, max: 9, step: 1 },
      { key: 'samples', kind: 'number', label: 'Search sample count', min: 8, max: 512, step: 8 },
    ],
  },

  // nurbs_match_srf_g3 — curvature-rate-continuity MatchSrf
  {
    op: 'nurbs_match_srf_g3',
    label: 'Match Surface G3',
    icon: GitMerge,
    category: 'nurbs',
    caption: (
      'Match a NURBS surface edge to a target surface with G3 (curvature-rate) ' +
      'continuity. Modifies the first 4 rows of control points of the source ' +
      'surface. Requires degree ≥ 3 and ≥ 4 CP rows.'
    ),
    defaults: {
      match_edge: 'u0',
      degree_u: 5,
      degree_v: 3,
    },
    fields: [
      { key: 'match_edge', kind: 'select', label: 'Match edge', options: [
        { value: 'u0', label: 'u = 0 (south edge)' },
        { value: 'u1', label: 'u = 1 (north edge)' },
        { value: 'v0', label: 'v = 0 (west edge)' },
        { value: 'v1', label: 'v = 1 (east edge)' },
      ] },
      { key: 'degree_u', kind: 'number', label: 'Source degree U', min: 3, max: 9, step: 1 },
      { key: 'degree_v', kind: 'number', label: 'Source degree V', min: 3, max: 9, step: 1 },
    ],
  },

  // nurbs_match_surface_g3 — full MatchSurface G3 (match_srf.py)
  {
    op: 'nurbs_match_surface_g3',
    label: 'Match Surface G3 (Full)',
    icon: GitMerge,
    category: 'nurbs',
    caption: (
      'Full G3 surface matching: adjust one surface to meet a target with G3 ' +
      'continuity along a shared boundary. Supports tangent scale and ' +
      'curvature rate controls. More flexible than the compact nurbs_match_srf_g3.'
    ),
    defaults: {
      target_edge: 'u0',
      match_continuity: 'G3',
    },
    fields: [
      { key: 'target_edge', kind: 'select', label: 'Target shared edge', options: [
        { value: 'u0', label: 'u = 0' },
        { value: 'u1', label: 'u = 1' },
        { value: 'v0', label: 'v = 0' },
        { value: 'v1', label: 'v = 1' },
      ] },
      { key: 'match_continuity', kind: 'select', label: 'Continuity target', options: [
        { value: 'G1', label: 'G1 (tangent)' },
        { value: 'G2', label: 'G2 (curvature)' },
        { value: 'G3', label: 'G3 (curvature-rate)' },
      ] },
    ],
  },

  // nurbs_analyze_isophotes — marching-squares isophote extractor
  {
    op: 'nurbs_analyze_isophotes',
    label: 'Isophote Analysis',
    icon: Eye,
    category: 'nurbs',
    caption: (
      'Compute isophote (constant normal-angle) lines on a NURBS surface via ' +
      'marching squares. Reports discontinuity count and fairness score ∈ [0,1]. ' +
      'Standard Class-A surface quality metric — complements zebra/curvature-comb analysis.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      num_u: 4,
      num_v: 4,
      view_direction: [0, 0, 1],
      angle_bands_deg: [0, 30, 60, 90],
      uv_samples_u: 80,
      uv_samples_v: 80,
      control_points: [],
      knots_u: [],
      knots_v: [],
    },
    fields: [
      { key: 'degree_u',      kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',      kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'num_u',         kind: 'number', label: 'CP count U', min: 2, step: 1 },
      { key: 'num_v',         kind: 'number', label: 'CP count V', min: 2, step: 1 },
      { key: 'uv_samples_u',  kind: 'number', label: 'UV grid resolution U', min: 8, max: 400, step: 8 },
      { key: 'uv_samples_v',  kind: 'number', label: 'UV grid resolution V', min: 8, max: 400, step: 8 },
    ],
  },

  // nurbs_surface_derivatives_analytic — analytic first/second partial derivatives
  {
    op: 'nurbs_surface_derivatives_analytic',
    label: 'Surface Derivatives',
    icon: Ruler,
    category: 'nurbs',
    caption: (
      'Compute analytic first and second partial derivatives (∂S/∂u, ∂S/∂v, ' +
      '∂²S/∂u², ∂²S/∂v², ∂²S/∂u∂v) at a UV point on a NURBS surface. ' +
      'Returns unit normal, Gaussian curvature K, and mean curvature H.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      control_points: [],
      knots_u: [],
      knots_v: [],
      u: 0.5,
      v: 0.5,
    },
    fields: [
      { key: 'degree_u', kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v', kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'u',        kind: 'number', label: 'u parameter', min: 0, max: 1, step: 0.01 },
      { key: 'v',        kind: 'number', label: 'v parameter', min: 0, max: 1, step: 0.01 },
    ],
  },

  // nurbs_loft_with_guide_rails — guide-rail loft (Piegl-Tiller §10.3)
  {
    op: 'nurbs_loft_with_guide_rails',
    label: 'Loft with Guide Rails',
    icon: Workflow,
    category: 'nurbs',
    caption: (
      'Loft a NURBS surface through cross-section curves while following guide rail ' +
      'curves (Piegl-Tiller §10.3 skinning + Gaussian displacement-blend). ' +
      'Mirrors the "guide-rail loft" in Rhino / Fusion 360.'
    ),
    defaults: {
      num_v_samples: 20,
      degree_v: 3,
      closed_v: false,
      cross_section_curves: [],
      guide_rail_curves: [],
    },
    fields: [
      { key: 'degree_v',       kind: 'number',  label: 'Loft direction degree', min: 1, max: 9, step: 1 },
      { key: 'num_v_samples',  kind: 'number',  label: 'V sample density', min: 4, max: 200, step: 4 },
      { key: 'closed_v',       kind: 'boolean', label: 'Close loft (periodic)' },
    ],
  },

  // nurbs_loft_with_rails_variable — variable rail-tangent Gordon loft
  {
    op: 'nurbs_loft_with_rails_variable',
    label: 'Loft with Variable Rails',
    icon: Workflow,
    category: 'nurbs',
    caption: (
      'Variable rail-tangent Gordon loft (Piegl-Tiller §10.4.3). ' +
      'Rail tangents can vary along each cross-section to match complex transitions. ' +
      'More flexible than guide-rail loft for swept-blend surfaces.'
    ),
    defaults: {
      sections: [],
      rails: [],
    },
    fields: [],
  },

  // nurbs_surface_area_exact — exact Gauss-Legendre surface area
  {
    op: 'nurbs_surface_area_exact',
    label: 'Surface Area (Exact)',
    icon: Ruler,
    category: 'nurbs',
    caption: (
      'Compute the exact surface area of a NURBS patch via Gauss-Legendre quadrature. ' +
      'More accurate than mesh-based approximation for smooth NURBS surfaces. ' +
      'Returns area_mm2, centroid_xyz, and error_estimate_mm2.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      control_points: [],
      knots_u: [],
      knots_v: [],
      quadrature_order: 8,
    },
    fields: [
      { key: 'degree_u',        kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',        kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'quadrature_order', kind: 'number', label: 'Gauss quadrature order', min: 2, max: 20, step: 1 },
    ],
  },

  // nurbs_offset_curve_2d — 2D planar curve offset
  {
    op: 'nurbs_offset_curve_2d',
    label: 'Offset Curve 2D',
    icon: Maximize2,
    category: 'nurbs',
    caption: (
      'Offset a 2D NURBS curve by a signed distance (positive = left of travel). ' +
      'Uses the Tiller-Hanson approximate offset + least-squares re-fit. ' +
      'Returns a new NurbsCurve of the same or higher degree.'
    ),
    defaults: {
      degree: 3,
      offset_distance_mm: 1.0,
      control_points: [],
      knots: [],
      samples: 32,
    },
    fields: [
      { key: 'degree',             kind: 'number', label: 'Curve degree', min: 1, max: 9, step: 1 },
      { key: 'offset_distance_mm', kind: 'number', label: 'Offset distance (mm)', step: 0.1 },
      { key: 'samples',            kind: 'number', label: 'Sample count for re-fit', min: 8, max: 256, step: 8 },
    ],
  },

  // nurbs_reparametrize_optimal — LSCM / ARAP optimal reparametrisation
  {
    op: 'nurbs_reparametrize_optimal',
    label: 'Reparametrize Optimal',
    icon: Shuffle,
    category: 'nurbs',
    caption: (
      'Reparametrize a NURBS surface to minimise UV distortion. ' +
      'Supports LSCM (angle-preserving, Lévy 2002) and ARAP (shape-preserving, Liu 2008). ' +
      'Returns distortion metrics and the reparametrized surface.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      control_points: [],
      knots_u: [],
      knots_v: [],
      method: 'lscm',
    },
    fields: [
      { key: 'degree_u', kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v', kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'method',   kind: 'select', label: 'Method', options: [
        { value: 'lscm', label: 'LSCM (angle-preserving)' },
        { value: 'arap', label: 'ARAP (shape-preserving)' },
      ] },
    ],
  },

  // nurbs_sample_surface_curvature_map — Gaussian / mean curvature heatmap
  {
    op: 'nurbs_sample_surface_curvature_map',
    label: 'Curvature Map',
    icon: Wand2,
    category: 'nurbs',
    caption: (
      'Sample Gaussian (K) and mean (H) curvature at a grid of UV points on a NURBS surface. ' +
      'Returns per-sample curvature values suitable for heatmap rendering. ' +
      'Uses analytic first and second partial derivatives.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      control_points: [],
      knots_u: [],
      knots_v: [],
      samples_u: 20,
      samples_v: 20,
    },
    fields: [
      { key: 'degree_u',  kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',  kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'samples_u', kind: 'number', label: 'Sample count U', min: 4, max: 200, step: 4 },
      { key: 'samples_v', kind: 'number', label: 'Sample count V', min: 4, max: 200, step: 4 },
    ],
  },

  // nurbs_compute_surface_cross_section — planar cross-section of a NURBS surface
  {
    op: 'nurbs_compute_surface_cross_section',
    label: 'Surface Cross-Section',
    icon: Scissors,
    category: 'nurbs',
    caption: (
      'Compute the planar cross-section of a NURBS surface with a cutting plane ' +
      '(Sederberg §7.3). Returns intersection points / polyline in 3D space. ' +
      'Use for generating section contours on freeform surfaces.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      control_points: [],
      knots_u: [],
      knots_v: [],
      plane_point: [0, 0, 0],
      plane_normal: [0, 0, 1],
      samples: 40,
    },
    fields: [
      { key: 'degree_u',       kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',       kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'plane_point[0]', kind: 'number', label: 'Plane point X (mm)' },
      { key: 'plane_point[1]', kind: 'number', label: 'Plane point Y (mm)' },
      { key: 'plane_point[2]', kind: 'number', label: 'Plane point Z (mm)' },
      { key: 'plane_normal[0]', kind: 'number', label: 'Normal X' },
      { key: 'plane_normal[1]', kind: 'number', label: 'Normal Y' },
      { key: 'plane_normal[2]', kind: 'number', label: 'Normal Z' },
      { key: 'samples',        kind: 'number', label: 'UV sample count', min: 8, max: 200, step: 8 },
    ],
  },

  // nurbs_shift_seam — shift the seam of a closed NURBS surface
  {
    op: 'nurbs_shift_seam',
    label: 'Shift Seam',
    icon: Shuffle,
    category: 'nurbs',
    caption: (
      'Shift the parametric seam of a closed (periodic) NURBS curve or surface. ' +
      'Useful for aligning the seam location before a boolean or loft. ' +
      'Exact — reparametrises the knot vector without changing geometry.'
    ),
    defaults: {
      surface: {},
      seam_u: 0.5,
    },
    fields: [
      { key: 'seam_u', kind: 'number', label: 'New seam u parameter', min: 0, max: 1, step: 0.05 },
    ],
  },

  // nurbs_trim_loop_heal — heal degenerate trim loops
  {
    op: 'nurbs_trim_loop_heal',
    label: 'Trim Loop Heal',
    icon: Wand2,
    category: 'nurbs',
    caption: (
      'Heal a degenerate or self-intersecting NURBS trim loop by closing gaps, ' +
      'removing spikes, and re-ordering edge segments. ' +
      'Returns a cleaned outer trim loop suitable for surface trimming.'
    ),
    defaults: {
      outer: [],
      tolerance: 1e-4,
      remove_spikes: true,
    },
    fields: [
      { key: 'tolerance',     kind: 'number',  label: 'Gap close tolerance (mm)', min: 1e-9, step: 1e-4 },
      { key: 'remove_spikes', kind: 'boolean', label: 'Remove spike segments' },
    ],
  },

  // nurbs_composite_g2_audit — audit G0/G1/G2 joints in a curve chain
  {
    op: 'nurbs_composite_g2_audit',
    label: 'Composite G2 Audit',
    icon: Shield,
    category: 'nurbs',
    caption: (
      'Audit the G0/G1/G2 continuity at every joint in a composite NURBS curve chain. ' +
      'Returns per-joint residuals and a pass/fail summary for each continuity class. ' +
      'Pairs with nurbs_composite_g2_upgrade to fix failing joints.'
    ),
    defaults: {
      segments: [],
    },
    fields: [],
  },

  // nurbs_composite_g2_upgrade — upgrade joints to G2 continuity
  {
    op: 'nurbs_composite_g2_upgrade',
    label: 'Composite G2 Upgrade',
    icon: Wand2,
    category: 'nurbs',
    caption: (
      'Upgrade failing G0/G1/G2 joints in a composite NURBS curve chain to G2 ' +
      'by inserting a cubic Hermite or quintic Bézier blend segment at each joint. ' +
      'Returns the repaired chain with per-joint improvement statistics.'
    ),
    defaults: {
      segments: [],
      method: 'quintic_bezier',
    },
    fields: [
      { key: 'method', kind: 'select', label: 'Blend method', options: [
        { value: 'quintic_bezier',  label: 'Quintic Bézier (G2 exact)' },
        { value: 'cubic_hermite',   label: 'Cubic Hermite (G1 only)' },
      ] },
    ],
  },

  // nurbs_solid_boolean — NURBS-native solid CSG boolean
  {
    op: 'nurbs_solid_boolean',
    label: 'NURBS Solid Boolean',
    icon: Combine,
    category: 'nurbs',
    caption: (
      'Perform a CSG boolean (cut / fuse / common) on NURBS-faced solid bodies. ' +
      'Operates on axis-aligned bounding-box octants for simple convex bodies. ' +
      'For general non-convex bodies use the regular Boolean op with to_solid pre-step.'
    ),
    defaults: {
      lo_a: [0, 0, 0],
      hi_a: [10, 10, 10],
      lo_b: [5, 5, 5],
      hi_b: [15, 15, 15],
      op: 'cut',
    },
    fields: [
      { key: 'op', kind: 'select', label: 'Operation', options: [
        { value: 'cut',    label: 'Cut (A − B)' },
        { value: 'fuse',   label: 'Fuse (A ∪ B)' },
        { value: 'common', label: 'Common (A ∩ B)' },
      ] },
    ],
  },

  // nurbs_fillet_variable_g2 — variable-radius G2 fillet between two surfaces
  {
    op: 'nurbs_fillet_variable_g2',
    label: 'Variable Fillet G2',
    icon: Waves,
    category: 'nurbs',
    caption: (
      'Compute a variable-radius G2-continuous fillet strip between two NURBS surfaces. ' +
      'Radius can vary along the shared edge according to a ramp profile. ' +
      'Returns a trimmed blend surface sewn to both input faces.'
    ),
    defaults: {
      radius_start: 2.0,
      radius_end: 5.0,
      samples: 20,
    },
    fields: [
      { key: 'radius_start', kind: 'number', label: 'Radius at start (mm)', min: 0.001, step: 0.1 },
      { key: 'radius_end',   kind: 'number', label: 'Radius at end (mm)',   min: 0.001, step: 0.1 },
      { key: 'samples',      kind: 'number', label: 'Sample count', min: 4, max: 128, step: 4 },
    ],
  },

  // nurbs_normal_curvature_at_point — Meusnier normal curvature at UV point
  {
    op: 'nurbs_normal_curvature_at_point',
    label: 'Normal Curvature at Point',
    icon: Ruler,
    category: 'nurbs',
    caption: (
      'Compute normal curvature κ_n at a UV point on a NURBS surface in a given ' +
      'direction (Meusnier\'s theorem, do Carmo §3.2). ' +
      'Returns κ_n, principal curvatures κ₁/κ₂, Gaussian K, mean H, and principal directions.'
    ),
    defaults: {
      degree_u: 3,
      degree_v: 3,
      control_points: [],
      knots_u: [],
      knots_v: [],
      u: 0.5,
      v: 0.5,
      direction_uv: [1, 0],
    },
    fields: [
      { key: 'degree_u',        kind: 'number', label: 'Degree U', min: 1, max: 9, step: 1 },
      { key: 'degree_v',        kind: 'number', label: 'Degree V', min: 1, max: 9, step: 1 },
      { key: 'u',               kind: 'number', label: 'u parameter', min: 0, max: 1, step: 0.01 },
      { key: 'v',               kind: 'number', label: 'v parameter', min: 0, max: 1, step: 0.01 },
      { key: 'direction_uv[0]', kind: 'number', label: 'Direction U component' },
      { key: 'direction_uv[1]', kind: 'number', label: 'Direction V component' },
    ],
  },

  // nurbs_curvature_metrics — curvature comb analysis on a curve
  {
    op: 'nurbs_curvature_metrics',
    label: 'Curvature Metrics',
    icon: Wand2,
    category: 'nurbs',
    caption: (
      'Compute curvature metrics along a NURBS curve: κ(t) comb, min/max/mean curvature, ' +
      'inflection parameter values, and fairness index. ' +
      'Use to assess smoothness and spot unwanted oscillations.'
    ),
    defaults: {
      degree: 3,
      control_points: [],
      samples: 64,
    },
    fields: [
      { key: 'degree',  kind: 'number', label: 'Curve degree', min: 1, max: 9, step: 1 },
      { key: 'samples', kind: 'number', label: 'Sample count', min: 8, max: 512, step: 8 },
    ],
  },

  // ── CAM — G-code emission, toolpath generation & analysis ─────────────────

  {
    op: 'cam_emit_gcode',
    label: 'Emit G-code',
    icon: Code,
    caption: (
      'Emit Fanuc RS-274/NGC G-code from a waypoint toolpath. ' +
      'Supports rapid (G00), linear (G01), arc CW/CCW (G02/G03), spindle on/off, tool change. ' +
      'Dialect: Fanuc 0i/18i/21i/30i + Haas + GRBL ≥1.1. ' +
      'Refs: NIST RS-274/NGC (Kramer et al. 2000); Smid CNC Programming Handbook (2008) §3.'
    ),
    defaults: { header_comment: '', program_number: 1, coord_decimals: 4 },
    fields: [
      { key: 'header_comment', kind: 'text',   label: 'Header comment' },
      { key: 'program_number', kind: 'number', label: 'Fanuc O-number (1–9999)', min: 1, max: 9999, step: 1 },
      { key: 'coord_decimals', kind: 'number', label: 'Coordinate decimal places', min: 1, max: 6, step: 1 },
    ],
  },

  {
    op: 'cam_emit_lathe_gcode',
    label: 'Lathe G-code (G71/G70)',
    icon: RotateCcw,
    caption: (
      'Emit Fanuc RS-274 lathe G-code (G71 rough turning + G70 finish turning) from a 2-D axis-symmetric profile. ' +
      'Profile: [[Z_mm, X_radius_mm], ...] pairs. stock_x_mm: initial stock radius. ' +
      'Dialect: Fanuc 0i-TF/30i ONLY. ' +
      'Refs: NIST RS-274/NGC (Kramer et al. 2000); Smid CNC Programming Handbook (2008) §6.'
    ),
    defaults: {
      stock_x_mm: 25.0, stock_z_mm: 2.0, tool_id: 1, sfm: 600,
      ipr: 0.25, finish_ipr: 0.10, doc_mm: 2.0,
      finish_allow_x_mm: 0.5, finish_allow_z_mm: 0.1,
      retract_mm: 5.0, program_number: 1, header_comment: '',
    },
    fields: [
      { key: 'stock_x_mm',        kind: 'number', label: 'Stock radius (mm)', min: 0.001 },
      { key: 'stock_z_mm',        kind: 'number', label: 'Facing stock (mm)', min: 0 },
      { key: 'tool_id',           kind: 'number', label: 'Tool number (1–99)', min: 1, max: 99, step: 1 },
      { key: 'sfm',               kind: 'number', label: 'Surface speed (ft/min)', min: 1 },
      { key: 'ipr',               kind: 'number', label: 'Roughing feed (mm/rev)', min: 0.001, step: 0.01 },
      { key: 'finish_ipr',        kind: 'number', label: 'Finishing feed (mm/rev)', min: 0.001, step: 0.01 },
      { key: 'doc_mm',            kind: 'number', label: 'Depth of cut per pass (mm)', min: 0.001 },
      { key: 'finish_allow_x_mm', kind: 'number', label: 'Finish allowance X (mm)', min: 0 },
      { key: 'finish_allow_z_mm', kind: 'number', label: 'Finish allowance Z (mm)', min: 0 },
      { key: 'retract_mm',        kind: 'number', label: 'Rapid clearance (mm)', min: 0 },
      { key: 'program_number',    kind: 'number', label: 'Fanuc O-number', min: 1, max: 9999, step: 1 },
      { key: 'header_comment',    kind: 'text',   label: 'Header comment' },
    ],
  },

  {
    op: 'cam_verify_toolpath_collision',
    label: 'Collision Check',
    icon: Shield,
    caption: (
      'Segment-by-segment holder/spindle collision verifier. ' +
      'Builds flute + holder capsules at each sample point; checks against stock AABB and optional fixture mesh. ' +
      'Refs: Ericson (2005) §5.5 capsule-AABB; Möller (1997) §6 capsule-triangle.'
    ),
    defaults: {
      step_mm: 1.0, safety_margin_mm: 0.5,
      flute_radius_mm: 4.0, flute_length_mm: 20.0,
      holder_radius_mm: 10.0, holder_length_mm: 40.0,
    },
    fields: [
      { key: 'step_mm',          kind: 'number', label: 'Sample step (mm)', min: 0.01, step: 0.1 },
      { key: 'safety_margin_mm', kind: 'number', label: 'Safety margin (mm)', min: 0 },
      { key: 'flute_radius_mm',  kind: 'number', label: 'Flute radius (mm)', min: 0.001 },
      { key: 'flute_length_mm',  kind: 'number', label: 'Flute length (mm)', min: 0.001 },
      { key: 'holder_radius_mm', kind: 'number', label: 'Holder radius (mm)', min: 0.001 },
      { key: 'holder_length_mm', kind: 'number', label: 'Holder length (mm)', min: 0.001 },
    ],
  },

  {
    op: 'cam_optimize_feedrate_lookahead',
    label: 'Feedrate Lookahead',
    icon: Gauge,
    caption: (
      'Two-pass feedrate optimiser (forward accel + backward decel) with corner-blend velocity capping. ' +
      'Optional S-curve (jerk-limited) scheduling per Erkorkmaz-Altintas (2001) §3.3. ' +
      'Refs: Erkorkmaz & Altintas (2001) IJMTM 41(9); Altintas (2012) Manufacturing Automation §5.7.'
    ),
    defaults: {
      target_feedrate_mm_per_min: 3000,
      max_accel_mm_per_s2: 500,
      blend_radius_mm: 0.5,
      profile_type: 'trapezoidal',
    },
    fields: [
      { key: 'target_feedrate_mm_per_min', kind: 'number', label: 'Target feedrate (mm/min)', min: 1 },
      { key: 'max_accel_mm_per_s2',        kind: 'number', label: 'Max acceleration (mm/s²)', min: 0.001 },
      { key: 'blend_radius_mm',            kind: 'number', label: 'Corner blend radius (mm)', min: 0 },
      { key: 'profile_type', kind: 'select', label: 'Velocity profile', options: [
        { value: 'trapezoidal', label: 'Trapezoidal' },
        { value: 's-curve',     label: 'S-curve (jerk-limited)' },
      ] },
    ],
  },

  {
    op: 'cam_linearize_arcs',
    label: 'Linearise Arcs',
    icon: RefreshCw,
    caption: (
      'Convert G02/G03 arc commands to G01 linear segments using chord-error tolerance. ' +
      'For legacy controllers without circular interpolation (Mach3, plasma, laser). ' +
      'Refs: NIST RS-274/NGC §3.5.3; MH 31e §1130.'
    ),
    defaults: { max_chord_error_mm: 0.025, min_segment_length_mm: 0.05 },
    fields: [
      { key: 'gcode_text',            kind: 'text',   label: 'G-code program text' },
      { key: 'max_chord_error_mm',    kind: 'number', label: 'Max chord error (mm)', min: 0.001, step: 0.001 },
      { key: 'min_segment_length_mm', kind: 'number', label: 'Min segment length (mm)', min: 0.001, step: 0.001 },
    ],
  },

  {
    op: 'cam_validate_chip_load',
    label: 'Validate Chip Load',
    icon: BarChart2,
    caption: (
      'Validate feed-per-tooth against Sandvik / Kennametal / Harvey Tool catalog ranges. ' +
      'Detects radial chip thinning (ae < D/2) and warns on over-feed or rubbing. ' +
      'Refs: Sandvik CoroPlus Milling Technical Guide (2024); MH 31e §1136.'
    ),
    defaults: {
      material: 'steel-1018', tool_diameter_mm: 12.0, num_flutes: 4,
      vc_m_per_min: 100, fz_mm_per_tooth: 0.05, ae_mm: 6.0, ap_mm: 5.0,
      tool_coating: 'TiAlN',
    },
    fields: [
      { key: 'material', kind: 'select', label: 'Workpiece material', options: [
        { value: 'steel-1018',       label: 'Steel 1018 (low carbon)' },
        { value: 'steel-4140-soft',  label: 'Steel 4140 soft' },
        { value: 'stainless-304',    label: 'Stainless 304' },
        { value: 'aluminum-6061',    label: 'Aluminium 6061' },
        { value: 'titanium-Ti6Al4V', label: 'Titanium Ti6Al4V' },
        { value: 'cast-iron-grey',   label: 'Cast iron (grey)' },
        { value: 'plastic-acetal',   label: 'Plastic (acetal)' },
      ] },
      { key: 'tool_diameter_mm', kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'num_flutes',       kind: 'number', label: 'Flute count', min: 1, max: 12, step: 1 },
      { key: 'vc_m_per_min',     kind: 'number', label: 'Cutting speed Vc (m/min)', min: 1 },
      { key: 'fz_mm_per_tooth',  kind: 'number', label: 'Feed per tooth fz (mm)', min: 0.001, step: 0.001 },
      { key: 'ae_mm',            kind: 'number', label: 'Radial DOC ae (mm)', min: 0.001 },
      { key: 'ap_mm',            kind: 'number', label: 'Axial DOC ap (mm)', min: 0.001 },
      { key: 'tool_coating', kind: 'select', label: 'Tool coating', options: [
        { value: 'TiAlN',       label: 'TiAlN' },
        { value: 'TiN',         label: 'TiN' },
        { value: 'AlCrN',       label: 'AlCrN' },
        { value: 'diamond-CVD', label: 'Diamond CVD' },
        { value: 'uncoated',    label: 'Uncoated' },
      ] },
    ],
  },

  {
    op: 'cam_check_dry_machining',
    label: 'Dry Machining Check',
    icon: Wind,
    caption: (
      'Check whether dry machining is feasible for the given material, coating, and cutting conditions. ' +
      'Returns recommendation, tool-life reduction factor, and minimum coating required. ' +
      'Refs: Sandvik Coromant Dry Machining Guide (2024); ISO 8688-1:1989.'
    ),
    defaults: {
      workpiece_material: 'steel-low-carbon', tool_coating: 'TiAlN',
      vc_m_per_min: 80, fz_mm_per_tooth: 0.05, ae_mm: 6.0, ap_mm: 5.0,
      tool_diameter_mm: 12.0, operation: 'milling-roughing',
    },
    fields: [
      { key: 'workpiece_material', kind: 'select', label: 'Workpiece material', options: [
        { value: 'steel-low-carbon',           label: 'Steel — low carbon' },
        { value: 'steel-medium-carbon',         label: 'Steel — medium carbon' },
        { value: 'steel-stainless-austenitic',  label: 'Stainless (austenitic)' },
        { value: 'cast-iron-grey',              label: 'Cast iron (grey)' },
        { value: 'aluminum-wrought',            label: 'Aluminium (wrought)' },
        { value: 'aluminum-cast',               label: 'Aluminium (cast)' },
        { value: 'titanium-Ti6Al4V',            label: 'Titanium Ti6Al4V' },
        { value: 'nickel-inconel-718',          label: 'Nickel / Inconel 718' },
      ] },
      { key: 'tool_coating', kind: 'select', label: 'Tool coating', options: [
        { value: 'TiAlN', label: 'TiAlN' }, { value: 'TiN', label: 'TiN' },
        { value: 'AlCrN', label: 'AlCrN' }, { value: 'diamond-CVD', label: 'Diamond CVD' },
        { value: 'uncoated', label: 'Uncoated' },
      ] },
      { key: 'vc_m_per_min',     kind: 'number', label: 'Cutting speed Vc (m/min)', min: 1 },
      { key: 'fz_mm_per_tooth',  kind: 'number', label: 'Feed per tooth fz (mm)', min: 0.001, step: 0.001 },
      { key: 'ae_mm',            kind: 'number', label: 'Radial DOC ae (mm)', min: 0.001 },
      { key: 'ap_mm',            kind: 'number', label: 'Axial DOC ap (mm)', min: 0.001 },
      { key: 'tool_diameter_mm', kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'operation', kind: 'select', label: 'Operation', options: [
        { value: 'milling-roughing',  label: 'Milling — roughing' },
        { value: 'milling-finishing', label: 'Milling — finishing' },
        { value: 'drilling',          label: 'Drilling' },
        { value: 'turning',           label: 'Turning' },
      ] },
    ],
  },

  {
    op: 'cam_generate_face_mill_path',
    label: 'Face Mill Path',
    icon: Layers,
    caption: (
      'Zig-zag face-milling G-code toolpath for a rectangular pocket. ' +
      '70 % stepover default; climb milling preferred (MH 31e §1136). ' +
      'LIMITATION: 2.5D pocket only; no helical entry; no G41/G42.'
    ),
    defaults: {
      xmin_mm: 0, ymin_mm: 0, xmax_mm: 100, ymax_mm: 80,
      depth_mm: 3.0, tool_diameter_mm: 16.0, stepover_pct: 70,
      feed_mm_per_min: 800, spindle_rpm: 3000,
      rapid_clearance_mm: 5.0, climb_milling: true,
    },
    fields: [
      { key: 'xmin_mm',            kind: 'number', label: 'Pocket Xmin (mm)' },
      { key: 'ymin_mm',            kind: 'number', label: 'Pocket Ymin (mm)' },
      { key: 'xmax_mm',            kind: 'number', label: 'Pocket Xmax (mm)' },
      { key: 'ymax_mm',            kind: 'number', label: 'Pocket Ymax (mm)' },
      { key: 'depth_mm',           kind: 'number', label: 'Axial depth (mm)', min: 0.001 },
      { key: 'tool_diameter_mm',   kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'stepover_pct',       kind: 'number', label: 'Stepover (%)', min: 10, max: 100, step: 1 },
      { key: 'feed_mm_per_min',    kind: 'number', label: 'Feed (mm/min)', min: 1 },
      { key: 'spindle_rpm',        kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'rapid_clearance_mm', kind: 'number', label: 'Rapid clearance (mm)', min: 0 },
      { key: 'climb_milling',      kind: 'boolean', label: 'Climb milling' },
    ],
  },

  {
    op: 'cam_generate_peck_drill_cycle',
    label: 'Peck Drill (G83)',
    icon: Drill,
    caption: (
      'G83 deep-hole peck-drilling canned cycle. ' +
      'Follows NIST RS-274/NGC §3.8.4 and MH 31e §1132 peck-depth guidelines. ' +
      'Returns G-code, peck count, and cycle-time estimate.'
    ),
    defaults: {
      x_mm: 0, y_mm: 0, depth_mm: 20,
      peck_depth_mm: 5, retract_mm: 2.0,
      feed_mm_per_min: 120, dwell_s: 0,
    },
    fields: [
      { key: 'x_mm',            kind: 'number', label: 'Hole centre X (mm)' },
      { key: 'y_mm',            kind: 'number', label: 'Hole centre Y (mm)' },
      { key: 'depth_mm',        kind: 'number', label: 'Hole depth (mm)', min: 0.001 },
      { key: 'peck_depth_mm',   kind: 'number', label: 'Peck depth per stroke (mm)', min: 0.001 },
      { key: 'retract_mm',      kind: 'number', label: 'R-plane clearance (mm)', min: 0 },
      { key: 'feed_mm_per_min', kind: 'number', label: 'Feed (mm/min)', min: 1 },
      { key: 'dwell_s',         kind: 'number', label: 'Dwell at bottom (s)', min: 0 },
    ],
  },

  {
    op: 'cam_generate_tap_cycle',
    label: 'Tap Cycle (G84/G74)',
    icon: Wrench,
    caption: (
      'G84 (right-hand) / G74 (left-hand) rigid tapping canned cycle. ' +
      'Feed = pitch × rpm per MH 31e §1934. M29 Sxxxx emitted for Fanuc rigid-tap mode. ' +
      'Refs: NIST RS-274/NGC §3.8.4; Fanuc 0i/30i rigid-tap conventions.'
    ),
    defaults: {
      x_mm: 0, y_mm: 0, depth_mm: 15,
      thread_pitch_mm: 1.0, spindle_rpm: 800,
      direction: 'right', rigid_tap: true,
    },
    fields: [
      { key: 'x_mm',            kind: 'number', label: 'Hole centre X (mm)' },
      { key: 'y_mm',            kind: 'number', label: 'Hole centre Y (mm)' },
      { key: 'depth_mm',        kind: 'number', label: 'Tap depth (mm)', min: 0.001 },
      { key: 'thread_pitch_mm', kind: 'number', label: 'Thread pitch (mm)', min: 0.001, step: 0.05 },
      { key: 'spindle_rpm',     kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'direction', kind: 'select', label: 'Thread direction', options: [
        { value: 'right', label: 'Right-hand (G84)' },
        { value: 'left',  label: 'Left-hand (G74)' },
      ] },
      { key: 'rigid_tap', kind: 'boolean', label: 'Rigid tap (emit M29)' },
    ],
  },

  {
    op: 'cam_generate_boring_cycle',
    label: 'Boring Cycle (G85/G86/G89)',
    icon: Drill,
    caption: (
      'G85/G86/G89 boring canned cycles. ' +
      'G85 = feed-out (Ra 0.8 µm); G86 = spindle-stop + rapid-out (Ra 1.6 µm); G89 = dwell + feed-out (Ra 0.4 µm). ' +
      'Refs: NIST RS-274/NGC §3.8.4; MH 31e §1162.'
    ),
    defaults: {
      x_mm: 0, y_mm: 0, depth_mm: 30,
      feed_mm_per_min: 50, spindle_rpm: 500,
      cycle_type: 'G85', dwell_s: 0, retract_mm: 2.0,
    },
    fields: [
      { key: 'x_mm',            kind: 'number', label: 'Hole centre X (mm)' },
      { key: 'y_mm',            kind: 'number', label: 'Hole centre Y (mm)' },
      { key: 'depth_mm',        kind: 'number', label: 'Bore depth (mm)', min: 0.001 },
      { key: 'feed_mm_per_min', kind: 'number', label: 'Feed (mm/min)', min: 1 },
      { key: 'spindle_rpm',     kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'cycle_type', kind: 'select', label: 'Cycle type', options: [
        { value: 'G85', label: 'G85 — feed-out precision bore (Ra 0.8 µm)' },
        { value: 'G86', label: 'G86 — spindle-stop + rapid-out (Ra 1.6 µm)' },
        { value: 'G89', label: 'G89 — dwell + feed-out finish bore (Ra 0.4 µm)' },
      ] },
      { key: 'dwell_s',    kind: 'number', label: 'Dwell at bottom (s, G89)', min: 0,
        showWhen: (n) => n.cycle_type === 'G89' },
      { key: 'retract_mm', kind: 'number', label: 'R-plane clearance (mm)', min: 0 },
    ],
  },

  {
    op: 'cam_generate_profile_roughing',
    label: 'Profile Roughing',
    icon: Layers,
    caption: (
      'Multi-pass 2D profile roughing: successive inward radial passes from stock offset to finish allowance. ' +
      'Implements MH 31e §1131 + Sandvik CoroPlus Contour Roughing (2024). ' +
      'LIMITATION: 2D polygon profile only; no pocket-with-islands.'
    ),
    defaults: {
      stock_offset_mm: 5.0, finish_allowance_mm: 0.3,
      cutter_diameter_mm: 10.0, depth_per_pass_mm: 3.0,
      total_depth_mm: 15.0, feed_mm_per_min: 600,
      spindle_rpm: 4000, rapid_clearance_mm: 5.0,
    },
    fields: [
      { key: 'stock_offset_mm',     kind: 'number', label: 'Stock offset (mm)', min: 0.001 },
      { key: 'finish_allowance_mm', kind: 'number', label: 'Finish allowance (mm)', min: 0 },
      { key: 'cutter_diameter_mm',  kind: 'number', label: 'Cutter diameter (mm)', min: 0.1 },
      { key: 'depth_per_pass_mm',   kind: 'number', label: 'Axial depth per pass (mm)', min: 0.001 },
      { key: 'total_depth_mm',      kind: 'number', label: 'Total depth (mm)', min: 0.001 },
      { key: 'feed_mm_per_min',     kind: 'number', label: 'Feed (mm/min)', min: 1 },
      { key: 'spindle_rpm',         kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'rapid_clearance_mm',  kind: 'number', label: 'Rapid clearance (mm)', min: 0 },
    ],
  },

  {
    op: 'cam_compute_chip_load',
    label: 'Chip Load Calc',
    icon: BarChart2,
    caption: (
      'Compute feed-per-tooth, radial chip-thinning factor (Krad), and MRR. ' +
      'Verifies against Sandvik CoroPlus recommended ranges. ' +
      'Refs: MH 31e §1136; Sandvik CoroPlus (2024); Stephenson-Agapiou §6.'
    ),
    defaults: {
      tool_diameter_mm: 12.0, num_flutes: 4,
      spindle_rpm: 5000, feed_mm_per_min: 800,
      radial_engagement_mm: 6.0, axial_depth_mm: 10.0,
      tool_material: 'carbide',
    },
    fields: [
      { key: 'tool_diameter_mm',     kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'num_flutes',           kind: 'number', label: 'Flute count', min: 1, step: 1 },
      { key: 'spindle_rpm',          kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'feed_mm_per_min',      kind: 'number', label: 'Table feed Vf (mm/min)', min: 1 },
      { key: 'radial_engagement_mm', kind: 'number', label: 'Radial DOC ae (mm)', min: 0.001 },
      { key: 'axial_depth_mm',       kind: 'number', label: 'Axial DOC ap (mm)', min: 0.001 },
      { key: 'tool_material', kind: 'select', label: 'Tool material', options: [
        { value: 'carbide', label: 'Carbide' },
        { value: 'HSS',     label: 'HSS' },
        { value: 'ceramic', label: 'Ceramic' },
      ] },
      { key: 'work_material', kind: 'text', label: 'Work material (optional, e.g. steel_1018)' },
    ],
  },

  {
    op: 'cam_compute_turning_depth',
    label: 'Turning Depth Calc',
    icon: Settings,
    caption: (
      'Compute optimal radial DOC per pass and total roughing passes for a lathe turning operation. ' +
      'Refs: MH 31e §1148; Sandvik CoroPlus Turning Catalogue (2024). ' +
      'HONEST: straight cylindrical turning only — no CSS, profile, taper, or threading.'
    ),
    defaults: {
      stock_diameter_mm: 50.0, final_diameter_mm: 40.0,
      material: 'steel_1018', tool_nose_radius_mm: 0.8,
      feed_mm_per_rev: 0.25, spindle_rpm: 800,
      finish_pass_doc_mm: 0.5, max_roughing_doc_mm: 3.0,
      workpiece_length_mm: 100,
    },
    fields: [
      { key: 'stock_diameter_mm',   kind: 'number', label: 'Stock OD (mm)', min: 0.001 },
      { key: 'final_diameter_mm',   kind: 'number', label: 'Final OD (mm)', min: 0 },
      { key: 'material', kind: 'select', label: 'Material', options: [
        { value: 'steel_1018',    label: 'Steel 1018' },
        { value: 'aluminum_6061', label: 'Aluminium 6061' },
        { value: 'stainless_303', label: 'Stainless 303' },
      ] },
      { key: 'tool_nose_radius_mm', kind: 'number', label: 'Insert nose radius rε (mm)', min: 0.001, step: 0.1 },
      { key: 'feed_mm_per_rev',     kind: 'number', label: 'Feed (mm/rev)', min: 0.001, step: 0.01 },
      { key: 'spindle_rpm',         kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'finish_pass_doc_mm',  kind: 'number', label: 'Finish pass DOC (mm)', min: 0 },
      { key: 'max_roughing_doc_mm', kind: 'number', label: 'Max roughing DOC (mm)', min: 0.001 },
      { key: 'workpiece_length_mm', kind: 'number', label: 'Workpiece length (mm)', min: 0.001 },
    ],
  },

  {
    op: 'cam_audit_milling_dwells',
    label: 'Audit Dwells (G04)',
    icon: Activity,
    caption: (
      'Audit G04 dwell blocks in a G-code program: detect unnecessary dwells, ' +
      'compute total dwell time, flag dwells at unsafe Z heights. ' +
      'Refs: MH 31e §1140; NIST RS-274/NGC §3.5.'
    ),
    defaults: { max_dwell_s: 2.0 },
    fields: [
      { key: 'gcode_text',  kind: 'text',   label: 'G-code program text' },
      { key: 'max_dwell_s', kind: 'number', label: 'Max acceptable dwell (s)', min: 0, step: 0.1 },
    ],
  },

  {
    op: 'cam_check_coolant_flow',
    label: 'Coolant Flow Check',
    icon: Droplets,
    caption: (
      'Check coolant flow-rate and pressure adequacy for the cutting conditions. ' +
      'Refs: Sandvik CoroPlus §3; MH 31e §1140.'
    ),
    defaults: {
      flow_rate_l_per_min: 20.0, pressure_bar: 10.0,
      operation: 'milling-roughing',
      workpiece_material: 'steel-low-carbon',
      tool_diameter_mm: 12.0,
    },
    fields: [
      { key: 'flow_rate_l_per_min', kind: 'number', label: 'Flow rate (L/min)', min: 0 },
      { key: 'pressure_bar',        kind: 'number', label: 'Pressure (bar)', min: 0 },
      { key: 'operation', kind: 'select', label: 'Operation', options: [
        { value: 'milling-roughing',  label: 'Milling — roughing' },
        { value: 'milling-finishing', label: 'Milling — finishing' },
        { value: 'drilling',          label: 'Drilling' },
        { value: 'turning',           label: 'Turning' },
      ] },
      { key: 'workpiece_material', kind: 'select', label: 'Workpiece material', options: [
        { value: 'steel-low-carbon',           label: 'Steel — low carbon' },
        { value: 'steel-medium-carbon',         label: 'Steel — medium carbon' },
        { value: 'steel-stainless-austenitic',  label: 'Stainless (austenitic)' },
        { value: 'cast-iron-grey',              label: 'Cast iron (grey)' },
        { value: 'aluminum-wrought',            label: 'Aluminium (wrought)' },
        { value: 'aluminum-cast',               label: 'Aluminium (cast)' },
        { value: 'titanium-Ti6Al4V',            label: 'Titanium Ti6Al4V' },
        { value: 'nickel-inconel-718',          label: 'Nickel / Inconel 718' },
      ] },
      { key: 'tool_diameter_mm', kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
    ],
  },

  // ── 5-axis CAM operations ─────────────────────────────────────────────────

  {
    op: 'cam_5axis_finish',
    label: '5-axis Constant-Tilt Finish',
    icon: Cpu,
    caption: (
      '5-axis constant-tilt surface finishing: tool axis is held at tilt_deg off the drive-face normal ' +
      'while following iso-parametric paths. Kinematic family: head-table (A around X, B around Y). ' +
      'Posts: LinuxCNC (G43.4 TCP optional) and Fanuc. ' +
      'Strategy: contour_tilted for general surfaces; swarf (tilt=0) for side-cutting engagement. ' +
      'Dispatches cam_run with operation="5axis_finish". ' +
      'Refs: Altintas (2012) §7; Bohez (2002) Int J Mach Tools 42(7):827–840.'
    ),
    defaults: {
      file_id: '', tool_diameter: 6.0, step_over: 0.5, step_down: 1.0,
      feed_rate: 1200, spindle_speed: 12000, coolant: true,
      drive_face_id: 0, tilt_deg: 15, lead_deg: 0,
      kinematic_family: 'head_table', use_tcp: false,
      post_processor_5x: 'linuxcnc',
    },
    fields: [
      { key: 'file_id',          kind: 'text',   label: 'File ID (STEP)' },
      { key: 'tool_diameter',    kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'drive_face_id',    kind: 'number', label: 'Drive face index (0-based)', min: 0, step: 1 },
      { key: 'tilt_deg',         kind: 'number', label: 'Tilt off surface normal (°)', min: 0, max: 30 },
      { key: 'lead_deg',         kind: 'number', label: 'Lead/lag angle (°)', min: -30, max: 30 },
      { key: 'step_over',        kind: 'number', label: 'Step-over (mm)', min: 0.01 },
      { key: 'step_down',        kind: 'number', label: 'Step-down (mm)', min: 0.01 },
      { key: 'feed_rate',        kind: 'number', label: 'Feed rate (mm/min)', min: 1 },
      { key: 'spindle_speed',    kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'use_tcp',          kind: 'bool',   label: 'TCP G43.4 mode' },
      { key: 'post_processor_5x', kind: 'select', label: 'Post-processor', options: [
        { value: 'linuxcnc', label: 'LinuxCNC' },
        { value: 'fanuc',    label: 'Fanuc' },
      ] },
    ],
  },

  {
    op: 'cam_3plus2',
    label: '3+2 Indexed (5-axis)',
    icon: Cpu,
    caption: (
      '3+2 indexed 5-axis: tilts the spindle to a drive-face-aligned orientation, locks A/B rotaries, ' +
      'then runs a standard 3-axis sub-operation (face/pocket/contour/parallel_3d/waterline). ' +
      'No simultaneous 5-axis motion — safer for entry-level 5-axis machines. ' +
      'Dispatches cam_run with operation="3plus2". ' +
      'Refs: Altintas (2012) §7; Erdim & Lazoglu (2014) J Mach Sci Tech 18(3):472–491.'
    ),
    defaults: {
      file_id: '', tool_diameter: 6.0, step_over: 1.0, step_down: 1.0,
      feed_rate: 1000, spindle_speed: 10000, coolant: true,
      drive_face_id: 0, indexed_op: 'face',
      post_processor_5x: 'linuxcnc',
    },
    fields: [
      { key: 'file_id',       kind: 'text',   label: 'File ID (STEP)' },
      { key: 'tool_diameter', kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'drive_face_id', kind: 'number', label: 'Drive face index (0-based)', min: 0, step: 1 },
      { key: 'indexed_op', kind: 'select', label: '3-axis sub-operation', options: [
        { value: 'face',        label: 'Face mill' },
        { value: 'pocket',      label: 'Pocket' },
        { value: 'contour',     label: 'Contour' },
        { value: 'parallel_3d', label: 'Parallel 3D' },
        { value: 'waterline',   label: 'Waterline' },
      ] },
      { key: 'step_over',     kind: 'number', label: 'Step-over (mm)', min: 0.01 },
      { key: 'step_down',     kind: 'number', label: 'Step-down (mm)', min: 0.01 },
      { key: 'feed_rate',     kind: 'number', label: 'Feed rate (mm/min)', min: 1 },
      { key: 'spindle_speed', kind: 'number', label: 'Spindle RPM', min: 1 },
      { key: 'post_processor_5x', kind: 'select', label: 'Post-processor', options: [
        { value: 'linuxcnc', label: 'LinuxCNC' },
        { value: 'fanuc',    label: 'Fanuc' },
      ] },
    ],
  },

  {
    op: 'hsm_adaptive_pocket',
    label: 'Adaptive Pocket (HSM)',
    icon: Cpu,
    caption: (
      'Constant tool-engagement 2D pocket clearing via iterative inward polygon offsetting. ' +
      'Corner arcs inserted to keep engagement bounded. Pure Python; no opencamlib required.'
    ),
    defaults: {
      pocket_width_mm: 50.0, pocket_height_mm: 40.0,
      tool_diameter_mm: 10.0, step_over_mm: 4.0,
      feed_mm_per_min: 1200, plunge_feed_mm_per_min: 200,
    },
    fields: [
      { key: 'pocket_width_mm',        kind: 'number', label: 'Pocket width (mm)', min: 0.001 },
      { key: 'pocket_height_mm',       kind: 'number', label: 'Pocket height (mm)', min: 0.001 },
      { key: 'tool_diameter_mm',       kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'step_over_mm',           kind: 'number', label: 'Step-over (mm)', min: 0.001 },
      { key: 'feed_mm_per_min',        kind: 'number', label: 'Cutting feed (mm/min)', min: 1 },
      { key: 'plunge_feed_mm_per_min', kind: 'number', label: 'Plunge feed (mm/min)', min: 1 },
    ],
  },

  {
    op: 'hsm_trochoidal_slot',
    label: 'Trochoidal Slot (HSM)',
    icon: Cpu,
    caption: (
      'Trochoidal (looping) slot milling — full circles advancing along slot centreline. ' +
      'Keeps radial engagement small, exploiting chip-thinning throughout. ' +
      'Pure Python; no opencamlib required.'
    ),
    defaults: {
      slot_length_mm: 80.0, slot_width_mm: 12.0,
      tool_diameter_mm: 10.0, trochoid_radius_mm: 3.0,
      step_over_mm: 2.5, feed_mm_per_min: 2500,
    },
    fields: [
      { key: 'slot_length_mm',     kind: 'number', label: 'Slot length (mm)', min: 0.001 },
      { key: 'slot_width_mm',      kind: 'number', label: 'Slot width (mm)', min: 0.001 },
      { key: 'tool_diameter_mm',   kind: 'number', label: 'Tool diameter (mm)', min: 0.1 },
      { key: 'trochoid_radius_mm', kind: 'number', label: 'Trochoid radius (mm)', min: 0.001 },
      { key: 'step_over_mm',       kind: 'number', label: 'Step-over per loop (mm)', min: 0.001 },
      { key: 'feed_mm_per_min',    kind: 'number', label: 'Feed (mm/min)', min: 1 },
    ],
  },

  {
    op: 'hsm_rest_machining',
    label: 'Rest Machining (HSM)',
    icon: Cpu,
    caption: (
      'Raster-based uncleared-region detection + small-tool clearing. ' +
      'Marks pixels not swept by prior large-tool toolpath; connects uncleared clusters and clears with zigzag. ' +
      'Pure Python; no opencamlib required.'
    ),
    defaults: {
      large_tool_diameter_mm: 16.0, small_tool_diameter_mm: 6.0,
      pocket_width_mm: 100.0, pocket_height_mm: 80.0,
      feed_mm_per_min: 800, grid_resolution_mm: 0.5,
    },
    fields: [
      { key: 'large_tool_diameter_mm', kind: 'number', label: 'Prior tool diameter (mm)', min: 0.1 },
      { key: 'small_tool_diameter_mm', kind: 'number', label: 'Small tool diameter (mm)', min: 0.1 },
      { key: 'pocket_width_mm',        kind: 'number', label: 'Pocket width (mm)', min: 0.001 },
      { key: 'pocket_height_mm',       kind: 'number', label: 'Pocket height (mm)', min: 0.001 },
      { key: 'feed_mm_per_min',        kind: 'number', label: 'Feed (mm/min)', min: 1 },
      { key: 'grid_resolution_mm',     kind: 'number', label: 'Grid resolution (mm)', min: 0.01, step: 0.1 },
    ],
  },

  // ── Sketch ops ────────────────────────────────────────────────────────────
  // sketch_add_entity: add a geometric entity (point/line/circle/arc/ellipse/bspline)
  {
    op: 'sketch_add_entity',
    label: 'Add Entity',
    icon: Pencil,
    caption: 'Add a geometric entity (point, line, circle, arc, ellipse, bspline) to a .sketch file.',
    defaults: {
      file_path: '',
      entity: { type: 'line', x1: 0, y1: 0, x2: 10, y2: 0 },
      construction: false,
    },
    fields: [
      { key: 'file_path',    kind: 'sketch_picker', label: 'Sketch file' },
      { key: 'entity.type',  kind: 'select', label: 'Entity type', options: [
        { value: 'point',   label: 'Point' },
        { value: 'line',    label: 'Line' },
        { value: 'circle',  label: 'Circle' },
        { value: 'arc',     label: 'Arc' },
        { value: 'ellipse', label: 'Ellipse' },
        { value: 'bspline', label: 'B-Spline' },
      ] },
      { key: 'construction', kind: 'boolean', label: 'Construction geometry' },
    ],
  },
  // sketch_add_constraint: add a geometric or dimensional constraint
  {
    op: 'sketch_add_constraint',
    label: 'Add Constraint',
    icon: PenLine,
    caption: 'Add a geometric or dimensional constraint to a .sketch file.',
    defaults: {
      file_path: '',
      constraint: { type: 'coincident', entity_ids: [] },
    },
    fields: [
      { key: 'file_path',         kind: 'sketch_picker', label: 'Sketch file' },
      { key: 'constraint.type',   kind: 'select', label: 'Constraint type', options: [
        { value: 'coincident',    label: 'Coincident' },
        { value: 'horizontal',    label: 'Horizontal' },
        { value: 'vertical',      label: 'Vertical' },
        { value: 'parallel',      label: 'Parallel' },
        { value: 'perpendicular', label: 'Perpendicular' },
        { value: 'tangent',       label: 'Tangent' },
        { value: 'equal',         label: 'Equal' },
        { value: 'distance',      label: 'Distance' },
        { value: 'angle',         label: 'Angle' },
        { value: 'radius',        label: 'Radius' },
        { value: 'diameter',      label: 'Diameter' },
        { value: 'fixed',         label: 'Fixed (fully lock)' },
      ] },
    ],
  },
  // sketch_set_constraint_value: update a dimensional constraint value
  {
    op: 'sketch_set_constraint_value',
    label: 'Set Constraint Value',
    icon: SlidersHorizontal,
    caption: 'Update the value of a dimensional constraint (distance/angle/radius/diameter).',
    defaults: {
      file_path: '',
      constraint_id: '',
      value: 10,
    },
    fields: [
      { key: 'file_path',     kind: 'sketch_picker', label: 'Sketch file' },
      { key: 'constraint_id', kind: 'text',          label: 'Constraint id' },
      { key: 'value',         kind: 'number',        label: 'Value (mm or °)', min: 0 },
    ],
  },
  // sketch_delete_entity: delete an entity (cascade to constraints)
  {
    op: 'sketch_delete_entity',
    label: 'Delete Entity',
    icon: Eraser,
    caption: 'Delete a sketch entity by id — cascades to any edges/constraints referencing it.',
    defaults: {
      file_path: '',
      entity_id: '',
    },
    fields: [
      { key: 'file_path', kind: 'sketch_picker', label: 'Sketch file' },
      { key: 'entity_id', kind: 'text',          label: 'Entity id' },
    ],
  },
  // sketch_validate: check a sketch is fully constrained + closed
  {
    op: 'sketch_validate',
    label: 'Validate Sketch',
    icon: ScanLine,
    caption: 'Validate a sketch for constraint completeness and closed-wire topology.',
    defaults: { file_path: '' },
    fields: [
      { key: 'file_path', kind: 'sketch_picker', label: 'Sketch file' },
    ],
  },
  // sketch_carbon_copy: import all entities from another sketch as construction geometry
  {
    op: 'sketch_carbon_copy',
    label: 'Carbon Copy',
    icon: Sticker,
    caption: 'Import all entities from a source sketch into this sketch as construction geometry.',
    defaults: { file_path: '', source_path: '' },
    fields: [
      { key: 'file_path',   kind: 'sketch_picker', label: 'Target sketch' },
      { key: 'source_path', kind: 'sketch_picker', label: 'Source sketch' },
    ],
  },

  // ── Mesh ops ──────────────────────────────────────────────────────────────
  // mesh_repair_run: weld + unify normals + fill holes + remove degenerate faces
  {
    op: 'mesh_repair_run',
    label: 'Mesh Repair',
    icon: Wrench,
    caption: 'Full mesh repair pipeline: weld vertices → unify normals → fill holes → remove degenerate faces.',
    defaults: {
      verts: [],
      faces: [],
      tol: 1e-6,
    },
    fields: [
      { key: 'tol', kind: 'number', label: 'Weld tolerance (mm)', min: 1e-9, step: 1e-6 },
    ],
  },
  // mesh_boolean_run: CSG union/difference/intersection on two triangle meshes
  {
    op: 'mesh_boolean_run',
    label: 'Mesh Boolean',
    icon: Combine,
    caption: 'Triangle-mesh CSG boolean (union / difference / intersection) between mesh A and mesh B.',
    defaults: {
      verts_a: [],
      faces_a: [],
      verts_b: [],
      faces_b: [],
      operation: 'difference',
    },
    fields: [
      { key: 'operation', kind: 'select', label: 'Operation', options: [
        { value: 'union',        label: 'Union (A ∪ B)' },
        { value: 'difference',   label: 'Difference (A − B)' },
        { value: 'intersection', label: 'Intersection (A ∩ B)' },
      ] },
    ],
  },
  // mesh_diagnostics: volume, area, closed, manifold checks
  {
    op: 'mesh_diagnostics',
    label: 'Mesh Diagnostics',
    icon: ScanSearch,
    caption: 'Run volume, area, is_closed, and is_manifold diagnostics on a triangle mesh.',
    defaults: { verts: [], faces: [] },
    fields: [],
  },
  // mesh_to_nurbs_convert: fit NURBS patches to a triangle mesh
  {
    op: 'mesh_to_nurbs_convert',
    label: 'Mesh → NURBS',
    icon: Spline,
    caption: 'Fit NURBS patches to a triangle mesh — required before OCCT Boolean / fillet ops.',
    defaults: {
      feature_ref: '',
      tolerance_mm: 0.1,
      max_degree: 5,
    },
    fields: [
      { key: 'feature_ref',  kind: 'feature_picker', label: 'Source mesh body' },
      { key: 'tolerance_mm', kind: 'number', label: 'Fit tolerance (mm)', min: 1e-4, step: 0.01 },
      { key: 'max_degree',   kind: 'number', label: 'Max NURBS degree',  min: 1, max: 9, step: 1 },
    ],
  },
  // mesh_apply_displacement_stack: multi-layer displacement map application
  {
    op: 'mesh_apply_displacement_stack',
    label: 'Displacement Stack',
    icon: Layers3,
    caption: 'Apply an ordered multi-layer displacement stack (add/subtract/multiply/replace) to a base mesh.',
    defaults: {
      base_vertices_xyz: [],
      base_normals_xyz: [],
      layers: [],
    },
    fields: [],
  },
  // mesh_sculpt_brush: Inflate / Crease / Smooth / Pinch sculpt stroke
  {
    op: 'mesh_sculpt_brush',
    label: 'Sculpt Brush',
    icon: Wand2,
    caption: 'Apply a single sculpt-brush stroke (Inflate/Crease/Smooth/Smooth-Taubin/Pinch) to a mesh.',
    defaults: {
      position_xyz_mm: [0, 0, 0],
      radius_mm: 5,
      brush_type: 'inflate',
      strength: 0.5,
    },
    fields: [
      { key: 'radius_mm',  kind: 'number', label: 'Brush radius (mm)', min: 0.001 },
      { key: 'brush_type', kind: 'select', label: 'Brush type', options: [
        { value: 'inflate',       label: 'Inflate' },
        { value: 'crease',        label: 'Crease' },
        { value: 'smooth',        label: 'Smooth (centroid)' },
        { value: 'smooth-taubin', label: 'Smooth Taubin (anti-shrink)' },
        { value: 'pinch',         label: 'Pinch' },
      ] },
      { key: 'strength', kind: 'number', label: 'Strength (−1..1)', min: -1, max: 1, step: 0.05 },
    ],
  },

  // ── Assembly ops ──────────────────────────────────────────────────────────
  // assembly_create: create a new empty assembly
  {
    op: 'assembly_create',
    label: 'New Assembly',
    icon: Boxes,
    caption: 'Create a new empty assembly and return its serialised state. Pass the assembly dict to subsequent assembly calls.',
    defaults: { name: 'assembly' },
    fields: [
      { key: 'name', kind: 'text', label: 'Assembly name' },
    ],
  },
  // assembly_add_component: add a part instance to an assembly
  {
    op: 'assembly_add_component',
    label: 'Add Component',
    icon: Component,
    caption: 'Add a part instance (Component) to an assembly. The first component is fixed (ground).',
    defaults: {
      part_ref: '',
      label: '',
    },
    fields: [
      { key: 'part_ref', kind: 'text', label: 'Part reference (file id or part number)' },
      { key: 'label',    kind: 'text', label: 'Instance label (optional)' },
    ],
  },
  // assembly_add_mate: add a constraint between two components
  {
    op: 'assembly_add_mate',
    label: 'Add Mate',
    icon: GitMerge,
    caption: 'Add a geometric constraint (Mate) between two component instances in the assembly.',
    defaults: {
      component_a_id: '',
      component_b_id: '',
      mate_type: 'coincident',
      offset_mm: 0,
      angle_deg: 0,
    },
    fields: [
      { key: 'component_a_id', kind: 'text', label: 'Component A id' },
      { key: 'component_b_id', kind: 'text', label: 'Component B id' },
      { key: 'mate_type', kind: 'select', label: 'Mate type', options: [
        { value: 'coincident',    label: 'Coincident (face-face flush)' },
        { value: 'parallel',      label: 'Parallel' },
        { value: 'perpendicular', label: 'Perpendicular' },
        { value: 'concentric',    label: 'Concentric (axis-axis)' },
        { value: 'distance',      label: 'Distance (offset)' },
        { value: 'angle',         label: 'Angle' },
        { value: 'tangent',       label: 'Tangent' },
        { value: 'fixed',         label: 'Fixed (lock all DOF)' },
      ] },
      { key: 'offset_mm',  kind: 'number', label: 'Offset (mm)',  min: 0, step: 0.1,
        showWhen: (n) => n.mate_type === 'distance' },
      { key: 'angle_deg',  kind: 'number', label: 'Angle (°)', min: -180, max: 180, step: 1,
        showWhen: (n) => n.mate_type === 'angle' },
    ],
  },
  // assembly_solve: solve the assembly and return resolved transforms + DOF
  {
    op: 'assembly_solve',
    label: 'Solve Assembly',
    icon: Workflow,
    caption: 'Solve all mate constraints and return resolved 4×4 transforms + per-component DOF status.',
    defaults: {},
    fields: [],
  },
  // assembly_bom: generate flat and indented BOM with quantity roll-up
  {
    op: 'assembly_bom',
    label: 'Bill of Materials',
    icon: LayoutDashboard,
    caption: 'Generate a flat and indented BOM from the assembly with quantity roll-up.',
    defaults: {},
    fields: [],
  },
  // brep_assembly_interference: detect volume overlap between bodies in an assembly
  {
    op: 'brep_assembly_interference',
    label: 'Interference Check',
    icon: AlertTriangle,
    caption: 'Detect geometric interference (volume overlap) between assembly bodies. Returns severity and intersection volume.',
    defaults: {
      bodies: [],
      tol: 1e-6,
      clearance_min: 0,
    },
    fields: [
      { key: 'tol',           kind: 'number', label: 'Tolerance (mm)',            min: 1e-9, step: 1e-6 },
      { key: 'clearance_min', kind: 'number', label: 'Min clearance warning (mm)', min: 0, step: 0.1 },
    ],
  },

  // ── Drawing ops ───────────────────────────────────────────────────────────
  // drawing_auto_views: 6-view orthographic + isometric drawing
  {
    op: 'drawing_auto_views',
    label: 'Auto Views',
    icon: LayoutTemplate,
    caption: 'Generate 6-view orthographic + isometric drawing (ISO 128-30). Returns per-view visible/hidden polylines.',
    defaults: {
      projection_type: 'third_angle',
      include_iso: true,
      sheet: 'A3',
    },
    fields: [
      { key: 'projection_type', kind: 'select', label: 'Projection type', options: [
        { value: 'third_angle', label: 'Third angle (ANSI/ASME Y14.3)' },
        { value: 'first_angle', label: 'First angle (ISO/DIN)' },
      ] },
      { key: 'include_iso', kind: 'boolean', label: 'Include isometric view' },
      { key: 'sheet', kind: 'select', label: 'Sheet size', options: [
        { value: 'A0', label: 'A0' }, { value: 'A1', label: 'A1' },
        { value: 'A2', label: 'A2' }, { value: 'A3', label: 'A3' },
        { value: 'A4', label: 'A4' }, { value: 'LETTER', label: 'Letter' },
      ] },
      { key: 'scale', kind: 'number', label: 'Scale (0.5=1:2, auto if blank)', min: 0.01, step: 0.1 },
    ],
  },
  // drawing_auto_dimension_iso: ISO 129-1:2018 chain/baseline/mixed dimensioning
  {
    op: 'drawing_auto_dimension_iso',
    label: 'ISO Auto-Dim',
    icon: Ruler,
    caption: 'Generate ISO 129-1:2018 chain / baseline / mixed dimension lines for a drawing view.',
    defaults: {
      mode: 'chain',
    },
    fields: [
      { key: 'mode', kind: 'select', label: 'Dimensioning mode', options: [
        { value: 'chain',    label: 'Chain (§5.1)' },
        { value: 'baseline', label: 'Baseline (§5.1)' },
        { value: 'mixed',    label: 'Mixed' },
      ] },
    ],
  },
  // drawing_measurement_chain: extract inspection measurement chain from a part
  {
    op: 'drawing_measurement_chain',
    label: 'Measurement Chain',
    icon: Activity,
    caption: 'Extract a complete inspection measurement chain from a part — holes, faces, threads, GD&T anchored to a 3-datum frame (ASME Y14.5-2018 §3.4).',
    defaults: {
      body: { name: '', bbox: { length: 100, width: 50, height: 30 }, holes: [] },
    },
    fields: [],
  },
  // drawing_inspection_report: render inspection chain as structured text report
  {
    op: 'drawing_inspection_report',
    label: 'Inspection Report',
    icon: FileText,
    caption: 'Render an inspection measurement chain as a structured text report (ISO 129-1:2018 or ASME Y14.5-2018).',
    defaults: {
      format: 'iso129',
    },
    fields: [
      { key: 'format', kind: 'select', label: 'Report format', options: [
        { value: 'iso129',  label: 'ISO 129-1:2018' },
        { value: 'asme145', label: 'ASME Y14.5-2018' },
      ] },
    ],
  },
  // drawing_validate_iso: validate ISO 129-1:2018 compliance
  {
    op: 'drawing_validate_iso',
    label: 'Validate ISO Dims',
    icon: FileSearch,
    caption: 'Check a drawing view dict for ISO 129-1:2018 compliance: extension-line lengths, spacing, leader angles, orientation.',
    defaults: {},
    fields: [],
  },
  // drawing_oblique_projection: oblique cabinet / cavalier projection
  {
    op: 'drawing_oblique_projection',
    label: 'Oblique Projection',
    icon: SplitSquareHorizontal,
    caption: 'Generate a 2D oblique (cabinet or cavalier) projection of a body — useful for pictorial drawings.',
    defaults: {
      angle_deg: 45,
      scale_receding: 0.5,
    },
    fields: [
      { key: 'angle_deg',        kind: 'number', label: 'Recession angle (°)', min: 0, max: 90, step: 5 },
      { key: 'scale_receding',   kind: 'number', label: 'Receding scale (0.5=cabinet, 1=cavalier)', min: 0.1, max: 1, step: 0.1 },
    ],
  },
  // drawing_silhouette_projection: silhouette + visible edges for a given view
  {
    op: 'drawing_silhouette_projection',
    label: 'Silhouette',
    icon: Scan,
    caption: 'Extract silhouette curves + visible feature edges for a given view direction.',
    defaults: {
      view_direction: [0, 0, -1],
    },
    fields: [
      { key: 'view_direction[0]', kind: 'number', label: 'View dir X' },
      { key: 'view_direction[1]', kind: 'number', label: 'View dir Y' },
      { key: 'view_direction[2]', kind: 'number', label: 'View dir Z' },
    ],
  },

  // ── Geom / B-rep utility ops ──────────────────────────────────────────────
  // geom_check_face_planarity: check if a face is planar within tolerance
  {
    op: 'geom_check_face_planarity',
    label: 'Face Planarity',
    icon: AlignCenter,
    caption: 'Check whether a B-rep face is planar within a given tolerance — flags non-planar faces for downstream sheet-metal or drawing ops.',
    defaults: {
      target_id: '',
      face_id: -1,
      tolerance_mm: 0.01,
    },
    fields: [
      { key: 'target_id',    kind: 'feature_picker', label: 'Target body' },
      { key: 'face_id',      kind: 'face_picker_single', label: 'Face' },
      { key: 'tolerance_mm', kind: 'number', label: 'Planarity tolerance (mm)', min: 1e-6, step: 0.001 },
    ],
  },
  // geom_classify_edge_convexity: classify edges as convex / concave / flat
  {
    op: 'geom_classify_edge_convexity',
    label: 'Edge Convexity',
    icon: TrendingUp,
    caption: 'Classify B-rep edges as convex / concave / flat — useful for auto-fillet and DFM analysis.',
    defaults: {
      target_id: '',
      angle_tolerance_deg: 1,
    },
    fields: [
      { key: 'target_id',            kind: 'feature_picker', label: 'Target body' },
      { key: 'angle_tolerance_deg',  kind: 'number', label: 'Angle tolerance (°)', min: 0, step: 0.5 },
    ],
  },
  // brep_analyze_wall_thickness: minimum wall thickness + thin-region detection
  {
    op: 'brep_analyze_wall_thickness',
    label: 'Wall Thickness',
    icon: SlidersHorizontal,
    caption: 'Ray-cast minimum wall thickness analysis — detects thin regions below the manufacturable minimum.',
    defaults: {
      target_id: '',
      min_acceptable_mm: 1.0,
      ray_count: 500,
    },
    fields: [
      { key: 'target_id',        kind: 'feature_picker', label: 'Target body' },
      { key: 'min_acceptable_mm',kind: 'number', label: 'Min acceptable wall (mm)', min: 0.001 },
      { key: 'ray_count',        kind: 'number', label: 'Ray count', min: 100, max: 5000, step: 100 },
    ],
  },
  // brep_check_clearance: minimum gap between two bodies
  {
    op: 'brep_check_clearance',
    label: 'Clearance Check',
    icon: Maximize2,
    caption: 'Compute the minimum clearance (gap) between two B-rep bodies — flags collisions and tight fits.',
    defaults: {
      body_a_id: '',
      body_b_id: '',
      min_clearance_mm: 0.5,
    },
    fields: [
      { key: 'body_a_id',        kind: 'feature_picker', label: 'Body A' },
      { key: 'body_b_id',        kind: 'feature_picker', label: 'Body B' },
      { key: 'min_clearance_mm', kind: 'number', label: 'Required clearance (mm)', min: 0, step: 0.1 },
    ],
  },
  // brep_recognize_holes: detect cylindrical hole features
  {
    op: 'brep_recognize_holes',
    label: 'Recognize Holes',
    icon: Drill,
    caption: 'Detect and classify cylindrical hole features (through, blind, countersink, counterbore, thread) in a B-rep body.',
    defaults: {
      target_id: '',
      min_diameter_mm: 0.5,
    },
    fields: [
      { key: 'target_id',      kind: 'feature_picker', label: 'Target body' },
      { key: 'min_diameter_mm',kind: 'number', label: 'Min diameter (mm)', min: 0.001 },
    ],
  },
  // brep_verify_euler_topology: V − E + F = 2 (closed shell) Euler check
  {
    op: 'brep_verify_euler_topology',
    label: 'Euler Topology',
    icon: Network,
    caption: 'Verify B-rep Euler topology: V − E + F = 2 for a closed shell, flags non-manifold or invalid topology.',
    defaults: {
      target_id: '',
    },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
    ],
  },
  // brep_compute_inertia: mass, CG, inertia tensor
  {
    op: 'brep_compute_inertia',
    label: 'Mass Properties',
    icon: BarChart2,
    caption: 'Compute mass, centre of gravity, and inertia tensor for a B-rep solid given material density.',
    defaults: {
      target_id: '',
      density_g_per_cm3: 7.85,
    },
    fields: [
      { key: 'target_id',          kind: 'feature_picker', label: 'Target body' },
      { key: 'density_g_per_cm3',  kind: 'number', label: 'Density (g/cm³)', min: 0.001, step: 0.1 },
    ],
  },

  // ── Orphan wire-up batch (2026-06-01) ────────────────────────────────────
  // brep_check_face_developable: test if a face can be unrolled flat
  {
    op: 'brep_check_face_developable',
    label: 'Face Developability',
    icon: ScanLine,
    caption: 'Test whether a B-rep face is developable (Gaussian curvature ≈ 0 everywhere) — required for flat-pattern sheet metal or fabric cutting.',
    defaults: { target_id: '', tol_k: 1e-4 },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target face / body' },
      { key: 'tol_k',     kind: 'number', label: 'Curvature tolerance (1/mm²)', min: 1e-9, step: 1e-5 },
    ],
  },
  // brep_detect_undercuts: pull-direction undercut detection for mold / casting
  {
    op: 'brep_detect_undercuts',
    label: 'Undercut Detection',
    icon: Eye,
    caption: 'Detect faces that create undercuts relative to a pull direction — critical for injection-mold and casting DFM.',
    defaults: { target_id: '', pull_direction_xyz: [0, 0, 1] },
    fields: [
      { key: 'target_id',          kind: 'feature_picker', label: 'Target body' },
      { key: 'pull_direction_xyz', kind: 'text',           label: 'Pull direction [x,y,z]' },
    ],
  },
  // brep_non_manifold_check: detect T-junction edges and touching-cone vertices
  {
    op: 'brep_non_manifold_check',
    label: 'Non-Manifold Check',
    icon: AlertTriangle,
    caption: 'Detect T-junction edges, touching-cone vertices, and self-intersecting loops that make a B-rep body non-manifold.',
    defaults: { target_id: '' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
    ],
  },
  // brep_detect_features: feature recognition (pockets, bosses, ribs, holes)
  {
    op: 'brep_detect_features',
    label: 'Feature Recognition',
    icon: Scan,
    caption: 'Automatically recognise manufacturing features — pockets, bosses, ribs, slots, holes — from a B-rep body using face-adjacency topology.',
    defaults: { target_id: '' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
    ],
  },
  // brep_export_step_with_colors: STEP AP214 with per-face RGB color
  {
    op: 'brep_export_step_with_colors',
    label: 'STEP Export (colors)',
    icon: FileOutput,
    caption: 'Export B-rep body to STEP AP214 with per-face RGB colour annotations — compatible with CATIA, NX, and SolidWorks color import.',
    defaults: { target_id: '', output_path: 'export.step' },
    fields: [
      { key: 'target_id',   kind: 'feature_picker', label: 'Target body' },
      { key: 'output_path', kind: 'text',            label: 'Output file path' },
    ],
  },
  // brep_generate_variable_chamfer: variable-width chamfer along edge
  {
    op: 'brep_generate_variable_chamfer',
    label: 'Variable Chamfer',
    icon: Scissors,
    caption: 'Generate a variable-width chamfer along selected edges — width defined by start/end distances (linear blend) or by a control polygon.',
    defaults: { target_id: '', edge_ids: [], start_distance_mm: 1.0, end_distance_mm: 2.0 },
    fields: [
      { key: 'target_id',        kind: 'feature_picker', label: 'Target body' },
      { key: 'edge_ids',         kind: 'text',           label: 'Edge IDs (comma-separated)' },
      { key: 'start_distance_mm',kind: 'number', label: 'Start distance (mm)', min: 0.001, step: 0.1 },
      { key: 'end_distance_mm',  kind: 'number', label: 'End distance (mm)',   min: 0.001, step: 0.1 },
    ],
  },
  // brep_check_wire_closed: verify a wire forms a closed loop
  {
    op: 'brep_check_wire_closed',
    label: 'Wire Closed Check',
    icon: Route,
    caption: 'Verify that an ordered list of B-rep edges forms a closed, planar loop — used as a pre-condition before creating face geometry.',
    defaults: { edge_ids: [] },
    fields: [
      { key: 'edge_ids', kind: 'text', label: 'Edge IDs (comma-separated)' },
    ],
  },
  // geometry_topology_integrity_check: full body validity check
  {
    op: 'geometry_topology_integrity_check',
    label: 'Topology Integrity',
    icon: Shield,
    caption: 'Run a full B-rep body validity check: Euler characteristic, manifold edges, face orientation, and self-intersections.',
    defaults: { target_id: '' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target body' },
    ],
  },
  // surface_deviation_check: two-surface Hausdorff deviation measurement
  {
    op: 'surface_deviation_check',
    label: 'Surface Deviation',
    icon: Ruler,
    caption: 'Compute max / mean / RMS Hausdorff deviation between two surfaces — quality control for machined parts vs. nominal CAD.',
    defaults: { ref_id: '', meas_id: '', samples: 1000 },
    fields: [
      { key: 'ref_id',  kind: 'feature_picker', label: 'Reference surface' },
      { key: 'meas_id', kind: 'feature_picker', label: 'Measured surface' },
      { key: 'samples', kind: 'number', label: 'Sample count', min: 100, max: 10000, step: 100 },
    ],
  },
  // surface_naked_edge_detect: find open boundary edges on a surface body
  {
    op: 'surface_naked_edge_detect',
    label: 'Naked Edge Detect',
    icon: ScanSearch,
    caption: 'Detect naked (open boundary) edges on a surface body — essential before converting surfaces to a solid B-rep.',
    defaults: { target_id: '' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target surface body' },
    ],
  },
  // subd_apply_displacement: apply displacement map to SubD limit mesh
  {
    op: 'subd_apply_displacement',
    label: 'SubD Displacement',
    icon: Layers,
    caption: 'Apply a procedural or image-based displacement map to the SubD limit surface — creates fine surface detail without topology editing.',
    defaults: { target_id: '', amplitude_mm: 0.5, frequency: 8 },
    fields: [
      { key: 'target_id',    kind: 'feature_picker', label: 'Target SubD cage' },
      { key: 'amplitude_mm', kind: 'number', label: 'Amplitude (mm)', min: 0, step: 0.1 },
      { key: 'frequency',    kind: 'number', label: 'Frequency (waves)', min: 1, step: 1 },
    ],
  },
  // subd_check_osd_compatibility: verify cage is OpenSubDiv 3.5 compatible
  {
    op: 'subd_check_osd_compatibility',
    label: 'OSD Compatibility',
    icon: Boxes,
    caption: 'Check that a SubD cage is Pixar OpenSubDiv 3.5 compatible — validates vertex valence, crease sharpness range, and dart constraints.',
    defaults: { target_id: '' },
    fields: [
      { key: 'target_id', kind: 'feature_picker', label: 'Target SubD cage' },
    ],
  },
  // sheetmetal_compute_flat_pattern: DIN 6935 / K-factor flat-pattern calculation
  {
    op: 'sheetmetal_compute_flat_pattern',
    label: 'Flat Pattern',
    icon: Layers3,
    caption: 'Compute the flat-pattern (unfold) dimensions for a multi-bend sheet metal part using DIN 6935 K-factor bend allowance.',
    defaults: {
      material: 'steel-cold-rolled',
      thickness_mm: 2.0,
      length_mm: 100.0,
      width_mm: 50.0,
      bend_radius_mm: 3.0,
      bend_angle_deg: 90,
      flange_lengths_mm: [30, 40],
    },
    fields: [
      { key: 'material',          kind: 'select', label: 'Material', options: ['steel-cold-rolled','stainless-304','aluminum-5052','copper'] },
      { key: 'thickness_mm',      kind: 'number', label: 'Thickness (mm)',     min: 0.1, step: 0.1 },
      { key: 'length_mm',         kind: 'number', label: 'Part length (mm)',   min: 1 },
      { key: 'width_mm',          kind: 'number', label: 'Part width (mm)',    min: 1 },
      { key: 'bend_radius_mm',    kind: 'number', label: 'Bend radius (mm)',   min: 0.1, step: 0.1 },
      { key: 'bend_angle_deg',    kind: 'number', label: 'Bend angle (°)',     min: 1, max: 180 },
      { key: 'flange_lengths_mm', kind: 'text',   label: 'Flange lengths mm (JSON array)' },
    ],
  },
  // sheetmetal_compute_hem: open/closed/teardrop/rolled hem flat development
  {
    op: 'sheetmetal_compute_hem',
    label: 'Hem Geometry',
    icon: Layers,
    caption: 'Compute the flat-pattern developed length for a sheet-metal hem (flange folded 180° back on itself). Supports open, closed, teardrop, and rolled hem types per Suchy §6 + DIN 6935 §4.3.',
    defaults: { hem_type: 'open', hem_radius_mm: 2.0, hem_length_mm: 8.0, sheet_thickness_mm: 1.0, k_factor: 0.4 },
    fields: [
      { key: 'hem_type',           kind: 'select', label: 'Hem type', options: ['open', 'closed', 'teardrop', 'rolled'] },
      { key: 'hem_radius_mm',      kind: 'number', label: 'Hem radius (mm)',      min: 0,   step: 0.1 },
      { key: 'hem_length_mm',      kind: 'number', label: 'Hem leg length (mm)',  min: 0.1, step: 0.5 },
      { key: 'sheet_thickness_mm', kind: 'number', label: 'Sheet thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'k_factor',           kind: 'number', label: 'K-factor',             min: 0.01, max: 0.99, step: 0.01 },
    ],
  },
  // sheetmetal_compute_jog: Z-offset jog (two opposing bends) flat development
  {
    op: 'sheetmetal_compute_jog',
    label: 'Jog Geometry',
    icon: SlidersHorizontal,
    caption: 'Compute the flat-pattern developed length for a sheet-metal jog (Z-offset, two opposing bends). Per Suchy §4.5 + DIN 6935: θ = arctan(h/L), flat = L + 2·BA.',
    defaults: { jog_height_mm: 10.0, jog_length_mm: 20.0, sheet_thickness_mm: 1.5, bend_radius_mm: 2.0, k_factor: 0.4 },
    fields: [
      { key: 'jog_height_mm',      kind: 'number', label: 'Jog height (mm)',      min: 0.1, step: 0.5 },
      { key: 'jog_length_mm',      kind: 'number', label: 'Jog land length (mm)', min: 0.1, step: 0.5 },
      { key: 'sheet_thickness_mm', kind: 'number', label: 'Sheet thickness (mm)', min: 0.1, step: 0.1 },
      { key: 'bend_radius_mm',     kind: 'number', label: 'Bend radius (mm)',     min: 0.1, step: 0.1 },
      { key: 'k_factor',           kind: 'number', label: 'K-factor',             min: 0.01, max: 0.99, step: 0.01 },
    ],
  },
  // sheetmetal_compute_multi_flange: chained N-bend flat development
  {
    op: 'sheetmetal_compute_multi_flange',
    label: 'Multi-Flange',
    icon: Repeat,
    caption: 'Compute flat-pattern for a chain of N flanges with N-1 bends, each with its own angle, radius, K-factor, and sheet thickness. Per Suchy §3 + DIN 6935.',
    defaults: {
      flanges: [
        { length_mm: 30, angle_deg: 90, radius_mm: 2, k_factor: 0.4, thickness_mm: 1.5 },
        { length_mm: 50, angle_deg: 90, radius_mm: 2, k_factor: 0.4, thickness_mm: 1.5 },
        { length_mm: 30, angle_deg: 90, radius_mm: 2, k_factor: 0.4, thickness_mm: 1.5 },
      ],
    },
    fields: [
      { key: 'flanges', kind: 'text', label: 'Flanges JSON (array of {length_mm, angle_deg, radius_mm, k_factor?, thickness_mm?})' },
    ],
  },
  // tolstack_analyze: 1-D tolerance stackup WC/RSS/Monte Carlo
  {
    op: 'tolstack_analyze',
    label: 'Tolerance Stackup',
    icon: SlidersHorizontal,
    caption: 'Analyze a 1-D tolerance chain: Worst Case, RSS, and Monte Carlo simulation to predict assembly variation.',
    defaults: { loop_closing_dimensions: [], required_gap_min_mm: 0.1, required_gap_max_mm: 1.0 },
    fields: [
      { key: 'loop_closing_dimensions', kind: 'text', label: 'Dimensions JSON (array of {nominal,tol} objects)' },
      { key: 'required_gap_min_mm',     kind: 'number', label: 'Min gap (mm)', step: 0.01 },
      { key: 'required_gap_max_mm',     kind: 'number', label: 'Max gap (mm)', step: 0.01 },
    ],
  },
  // brep_check_moldability: full mold DFM check (draft, undercuts, wall thickness)
  {
    op: 'brep_check_moldability',
    label: 'Moldability Check',
    icon: Wrench,
    caption: 'Full injection-mold DFM check: draft angle per face, undercut detection, parting line, and wall-thickness uniformity.',
    defaults: { target_id: '', pull_direction_xyz: [0, 0, 1], min_draft_deg: 1.0 },
    fields: [
      { key: 'target_id',          kind: 'feature_picker', label: 'Target body' },
      { key: 'pull_direction_xyz', kind: 'text',           label: 'Pull direction [x,y,z]' },
      { key: 'min_draft_deg',      kind: 'number', label: 'Min draft angle (°)', min: 0, step: 0.5 },
    ],
  },
  // brep_check_shell_walls: detect thin walls below manufacturing minimum
  {
    op: 'brep_check_shell_walls',
    label: 'Shell Wall Check',
    icon: Activity,
    caption: 'Detect shell / thin-wall regions below the minimum manufacturable thickness for milling, casting, or injection moulding.',
    defaults: { target_id: '', min_wall_mm: 1.0 },
    fields: [
      { key: 'target_id',  kind: 'feature_picker', label: 'Target body' },
      { key: 'min_wall_mm',kind: 'number', label: 'Min wall (mm)', min: 0.001, step: 0.1 },
    ],
  },
  // brep_apply_chamfer_recommendations: DFM-guided chamfer auto-apply
  {
    op: 'brep_apply_chamfer_recommendations',
    label: 'Auto Chamfer (DFM)',
    icon: Zap,
    caption: 'Automatically apply DFM-recommended chamfers to sharp-entry edges (tool runout relief, deburring allowance) based on manufacturing process.',
    defaults: { target_id: '', process: 'milling', chamfer_mm: 0.5 },
    fields: [
      { key: 'target_id',  kind: 'feature_picker', label: 'Target body' },
      { key: 'process',    kind: 'select', label: 'Process', options: ['milling','turning','casting','injection_mold'] },
      { key: 'chamfer_mm', kind: 'number', label: 'Chamfer size (mm)', min: 0.1, step: 0.1 },
    ],
  },
  // brep_apply_fillet_recommendations: DFM-guided fillet auto-apply
  {
    op: 'brep_apply_fillet_recommendations',
    label: 'Auto Fillet (DFM)',
    icon: Wand2,
    caption: 'Automatically apply DFM-recommended fillets to internal corners based on tool radius constraints for the target manufacturing process.',
    defaults: { target_id: '', process: 'milling', fillet_mm: 1.0 },
    fields: [
      { key: 'target_id',  kind: 'feature_picker', label: 'Target body' },
      { key: 'process',    kind: 'select', label: 'Process', options: ['milling','casting','injection_mold'] },
      { key: 'fillet_mm',  kind: 'number', label: 'Fillet radius (mm)', min: 0.1, step: 0.1 },
    ],
  },
  // surface_isocurve_extract: extract U/V iso-parameter curves from NURBS surface
  {
    op: 'surface_isocurve_extract',
    label: 'Extract Isocurves',
    icon: GitBranch,
    caption: 'Extract U-parameter or V-parameter iso-curves from a NURBS surface at specified parameter values — useful for toolpath seeding and surface analysis.',
    defaults: { target_id: '', direction: 'u', param_values: [0.25, 0.5, 0.75] },
    fields: [
      { key: 'target_id',    kind: 'feature_picker', label: 'Target surface' },
      { key: 'direction',    kind: 'select', label: 'Direction', options: ['u','v'] },
      { key: 'param_values', kind: 'text',           label: 'Parameter values (JSON array)' },
    ],
  },

  // ── GD&T annotation ops (ASME Y14.5-2018) ─────────────────────────────────
  // gdt_apply_datum — attach A/B/C datum to a face/edge/point on a drawing
  {
    op: 'gdt_apply_datum',
    label: 'Apply Datum',
    icon: AlignLeft,
    category: 'gdt',
    caption: 'Attach a datum reference (A/B/C/D) to a face, edge, or point on a drawing sheet or 3D body (MBD). Registers the datum label in the drawing datum registry per ASME Y14.5-2018 §4.',
    defaults: {
      feature_id:   'face-0',
      datum_letter: 'A',
      datum_role:   'primary',
      mbd_mode:     false,
    },
    fields: [
      { key: 'feature_id',   kind: 'text',    label: 'Feature ID (face/edge/point)' },
      { key: 'datum_letter', kind: 'select',  label: 'Datum letter',
        options: ['A','B','C','D','E','F'].map((l) => ({ value: l, label: l })) },
      { key: 'datum_role',   kind: 'select',  label: 'Role',
        options: [
          { value: 'primary',   label: 'Primary' },
          { value: 'secondary', label: 'Secondary' },
          { value: 'tertiary',  label: 'Tertiary' },
        ] },
      { key: 'mbd_mode',     kind: 'bool',    label: 'MBD mode (attach to 3D body)' },
    ],
  },
  // gdt_apply_tolerance — attach a feature control frame to a feature
  {
    op: 'gdt_apply_tolerance',
    label: 'Apply Tolerance (FCF)',
    icon: FileText,
    category: 'gdt',
    caption: 'Attach a feature control frame (FCF) tolerance to a drawing feature. Validates the FCF string, computes bonus tolerance for MMC/LMC modifiers, and writes the annotation node to the drawing model per ASME Y14.5-2018 §6.',
    defaults: {
      feature_id: 'hole-0',
      fcf_string: '⊕|⌀0.100Ⓜ|A|B|C',
      mbd_mode:   false,
    },
    fields: [
      { key: 'feature_id', kind: 'text', label: 'Feature ID' },
      { key: 'fcf_string', kind: 'text', label: 'FCF string (e.g. ⊕|⌀0.1Ⓜ|A|B|C)' },
      { key: 'mbd_mode',   kind: 'bool', label: 'MBD mode (attach to 3D body)' },
    ],
  },
  // gdt_validate_frame — structural well-formedness check per Y14.5-2018
  {
    op: 'gdt_validate_frame',
    label: 'Validate FCF',
    icon: Shield,
    category: 'gdt',
    caption: 'Structural well-formedness check for a GD&T feature control frame: symbol-modifier compatibility, datum requirements by tolerance category, duplicate-datum detection, bonus tolerance (MMC/LMC §6.3), and canonical string round-trip per ASME Y14.5-2018.',
    defaults: {
      fcf_string: '⊕|⌀0.500|A|B|C',
    },
    fields: [
      { key: 'fcf_string', kind: 'text', label: 'FCF string (e.g. ⊕|⌀0.5|A|B|C)' },
    ],
  },
  // gdt_validate_composite_frame — PLTZF/FRTZF composite frame check
  {
    op: 'gdt_validate_composite_frame',
    label: 'Validate Composite Frame',
    icon: Shield,
    category: 'gdt',
    caption: 'Validate stacked PLTZF/FRTZF composite feature control frames: R1 symbol match, R2 FRTZF ≤ PLTZF tolerance, R3 FRTZF datum refs are a subset of PLTZF datum refs per ASME Y14.5-2018 §10.5.2.',
    defaults: {
      feature_id: 'pattern-1',
    },
    fields: [
      { key: 'feature_id', kind: 'text', label: 'Feature ID' },
    ],
  },
  // gdt_compute_dimension_chain — tolerance stackup WC + RSS
  {
    op: 'gdt_compute_dimension_chain',
    label: 'Dimension Chain Stackup',
    icon: Ruler,
    category: 'gdt',
    caption: 'Compute worst-case (WC) and RSS statistical tolerance stack-up for a linear dimension chain. Returns nominal gap, WC min/max, and RSS min/max (3σ, 99.73%). Identifies the dominant link per ASME Y14.5-2018 §5.3 + Bralla §1.',
    defaults: {
      target_gap_min_mm: 0.0,
      target_gap_max_mm: 1.0,
    },
    fields: [
      { key: 'target_gap_min_mm', kind: 'number', label: 'Min acceptable gap (mm)', min: 0 },
      { key: 'target_gap_max_mm', kind: 'number', label: 'Max acceptable gap (mm)', min: 0 },
    ],
  },
]

const KIND_BY_OP = Object.fromEntries(FEATURE_KINDS.map((k) => [k.op, k]))

// Named exports for unit tests and external consumers.
export { FEATURE_KINDS, FEATURE_CATEGORIES }

const FEATURE_CATEGORIES = [
  { id: 'sketch',   label: 'Sketch-based',  ops: ['pad', 'boss_with_draft', 'pocket', 'cut_from_sketch', 'revolve', 'hole', 'hole_pattern', 'rib', 'helix'] },
  { id: 'modify',   label: 'Modify',        ops: [
    'fillet', 'chamfer', 'shell', 'push_pull', 'variable_radius_fillet',
    'to_solid', 'boolean', 'section', 'quad_remesh', 'delete_face', 'isotropic_remesh',
    // Coverage sweep additions
    'feature_draft', 'feature_mirror',
    'feature_tapped_hole', 'feature_thread_external', 'feature_hole_pattern_from_sketch',
  ] },
  { id: 'pattern',  label: 'Pattern',       ops: ['linear_pattern', 'polar_pattern', 'mirror_pattern', 'multi_transform'] },
  { id: 'surface',  label: 'Surfacing',     ops: ['sweep1', 'sweep2', 'loft', 'network_srf', 'blend_srf', 'blend_srf_g3', 'g3_chain_blend', 'fit_surface', 'surface_boolean', 'trim_by_curve', 'surface_curvature_combs', 'isophote_analysis', 'uv_unwrap'] },
  { id: 'analysis', label: 'Analysis',      ops: ['zebra_analysis', 'class_a_check', 'global_continuity_audit', 'imprint_curve'] },
  { id: 'gears',    label: 'Gears',         ops: ['gear_spur', 'gear_helical', 'gear_internal', 'gear_rack'] },
  { id: 'jewelry',  label: 'Jewelry',       ops: [
    // Gemstones
    'gemstone',
    // Settings v1–v4
    'jewelry_prong_head', 'jewelry_bezel', 'jewelry_channel', 'jewelry_pave',
    'jewelry_tension', 'jewelry_flush', 'jewelry_halo', 'jewelry_three_stone',
    'jewelry_cluster', 'jewelry_bar', 'jewelry_bead_grain', 'jewelry_gypsy_pave',
    'jewelry_illusion', 'jewelry_invisible',
    'jewelry_prong_variant', 'jewelry_head_gallery', 'jewelry_under_bezel',
    'jewelry_peg_setting', 'jewelry_coronet', 'jewelry_suspension_mount',
    'jewelry_vtip_protector', 'jewelry_bombe_cluster', 'jewelry_patterned_bezel',
    'jewelry_trellis_prong', 'jewelry_bar_channel_graduated',
    // Gem seat types
    'gem_seat', 'channel_seat', 'bezel_seat', 'fishtail_seat',
    // Gem seat cuts (coverage sweep additions)
    'jewelry_cut_baguette_channel_seat', 'jewelry_cut_cluster_halo_seat',
    'jewelry_cut_gypsy_seat', 'jewelry_cut_multi_stone_seat', 'jewelry_cut_pave_field_seat',
    // Ring ops
    'ring_shank', 'eternity_band', 'signet_ring', 'stacking_band_set',
    'contoured_band', 'solitaire_ring', 'mens_band', 'wedding_set',
    'cocktail_ring', 'bypass_ring',
    // Chain + composed pieces
    'chain_assembly', 'tennis_bracelet', 'station_necklace', 'lariat',
    'charm_bracelet', 'multi_strand', 'extender_chain',
    // Findings
    'finding',
    // Whole pieces
    'pendant', 'earrings', 'brooch', 'cufflink', 'bangle',
    // Decorative
    'decorative_apply',
  ] },
  { id: 'sheetmetal', label: 'Sheet Metal', ops: [
    'sheet_metal_flange', 'hem_sheet', 'jog_sheet', 'multi_flange',
    // Coverage sweep additions
    'sheet_metal_flat_pattern', 'sheet_metal_unfold',
  ] },
  { id: 'subd',      label: 'SubD / Mesh',  ops: [
    'subd_poke', 'subd_extrude_along', 'sculpt_brush', 'multires_evaluate', 'subd_deform_with_cage',
    'subd_inset_faces', 'subd_bridge_loops', 'subd_loop_subdivision',
    'subd_compute_stam_limit_tangents', 'subd_convert_to_g1_patches', 'subd_apply_crease_decay',
    'subd_collapse_edge', 'subd_sample_limit_normals', 'subd_compute_cage_area',
    'subd_evaluate_limit_normal', 'subd_extract_feature_curves', 'subd_export_usdc',
    'subd_geodesic_distance', 'subd_csg_union', 'subd_csg_difference', 'subd_csg_intersection',
    'subd_project_primitive', 'subd_symmetrize',
    'sdf_csg', 'retopo_snap',
    // Orphan wire-up 2026-06-01
    'subd_apply_displacement', 'subd_check_osd_compatibility',
  ] },
  { id: 'sketch_ops', label: 'Sketch Tools', ops: [
    'sketch_add_entity', 'sketch_add_constraint', 'sketch_set_constraint_value',
    'sketch_delete_entity', 'sketch_validate', 'sketch_carbon_copy',
  ] },
  { id: 'mesh_ops',   label: 'Mesh Ops',    ops: [
    'mesh_repair_run', 'mesh_boolean_run', 'mesh_diagnostics',
    'mesh_to_nurbs_convert', 'mesh_apply_displacement_stack', 'mesh_sculpt_brush',
  ] },
  { id: 'assembly',   label: 'Assembly',    ops: [
    'assembly_create', 'assembly_add_component', 'assembly_add_mate',
    'assembly_solve', 'assembly_bom', 'brep_assembly_interference',
  ] },
  { id: 'drawing',    label: 'Drawing',     ops: [
    'drawing_auto_views', 'drawing_auto_dimension_iso',
    'drawing_measurement_chain', 'drawing_inspection_report',
    'drawing_validate_iso', 'drawing_oblique_projection', 'drawing_silhouette_projection',
  ] },
  { id: 'brep_utils', label: 'B-rep Utils', ops: [
    'geom_check_face_planarity', 'geom_classify_edge_convexity',
    'brep_analyze_wall_thickness', 'brep_check_clearance',
    'brep_recognize_holes', 'brep_verify_euler_topology', 'brep_compute_inertia',
    // Orphan wire-up 2026-06-01
    'brep_check_face_developable', 'brep_detect_undercuts', 'brep_non_manifold_check',
    'brep_detect_features', 'brep_export_step_with_colors', 'brep_generate_variable_chamfer',
    'brep_check_wire_closed', 'geometry_topology_integrity_check',
    'brep_check_moldability', 'brep_check_shell_walls',
    'brep_apply_chamfer_recommendations', 'brep_apply_fillet_recommendations',
  ] },
  { id: 'surface_analysis', label: 'Surface Analysis', ops: [
    'surface_deviation_check', 'surface_naked_edge_detect', 'surface_isocurve_extract',
  ] },
  { id: 'manufacturing_dfm', label: 'Manufacturing / DFM', ops: [
    'sheetmetal_compute_flat_pattern',
    'sheetmetal_compute_hem',
    'sheetmetal_compute_jog',
    'sheetmetal_compute_multi_flange',
    'tolstack_analyze',
  ] },
  { id: 'weldment',  label: 'Weldment',     ops: ['gusset_plate', 'cope_notch'] },
  { id: 'bim',       label: 'BIM',          ops: ['bim_make_grid', 'bim_make_framing', 'bim_make_wall', 'bim_make_slab'] },
  { id: 'cam', label: 'CAM / Manufacturing', ops: [
    // G-code emission
    'cam_emit_gcode', 'cam_emit_lathe_gcode',
    // Toolpath generation
    'cam_generate_face_mill_path', 'cam_generate_peck_drill_cycle',
    'cam_generate_tap_cycle', 'cam_generate_boring_cycle',
    'cam_generate_profile_roughing',
    // 5-axis operations
    'cam_5axis_finish', 'cam_3plus2',
    // HSM strategies
    'hsm_adaptive_pocket', 'hsm_trochoidal_slot', 'hsm_rest_machining',
    // Toolpath analysis & validation
    'cam_verify_toolpath_collision', 'cam_optimize_feedrate_lookahead',
    'cam_linearize_arcs', 'cam_audit_milling_dwells',
    // Cutting physics
    'cam_compute_chip_load', 'cam_validate_chip_load',
    'cam_check_dry_machining', 'cam_check_coolant_flow',
    // Turning
    'cam_compute_turning_depth',
  ] },
  { id: 'nurbs',    label: 'NURBS',        ops: [
    // Degree manipulation
    'nurbs_degree_raise', 'nurbs_degree_lower',
    // Surface offset
    'nurbs_surface_offset', 'nurbs_surface_offset_robust',
    // Curve/surface projection + iso-curve extraction
    'nurbs_project_curve_to_surface',
    'nurbs_extract_iso_u', 'nurbs_extract_iso_v',
    // Split operations
    'nurbs_split_curve', 'nurbs_split_surface',
    // Curve analysis
    'nurbs_find_curve_inflections',
    'nurbs_curvature_metrics',
    'nurbs_offset_curve_2d',
    // Surface matching
    'nurbs_match_srf_g3', 'nurbs_match_surface_g3',
    // Surface analysis
    'nurbs_analyze_isophotes',
    'nurbs_surface_derivatives_analytic',
    'nurbs_surface_area_exact',
    'nurbs_sample_surface_curvature_map',
    'nurbs_normal_curvature_at_point',
    // Loft with rails
    'nurbs_loft_with_guide_rails', 'nurbs_loft_with_rails_variable',
    // Reparametrize + seam
    'nurbs_reparametrize_optimal', 'nurbs_shift_seam',
    // Cross-section + trim
    'nurbs_compute_surface_cross_section',
    'nurbs_trim_loop_heal',
    // Composite curve quality
    'nurbs_composite_g2_audit', 'nurbs_composite_g2_upgrade',
    // Boolean + fillet
    'nurbs_solid_boolean',
    'nurbs_fillet_variable_g2',
  ] },
  { id: 'gdt', label: 'GD&T / MBD', ops: [
    // Datum + FCF placement (drawing annotation + MBD)
    'gdt_apply_datum',
    'gdt_apply_tolerance',
    'gdt_validate_frame',
    'gdt_validate_composite_frame',
    'gdt_compute_dimension_chain',
  ] },
]

const DEBOUNCE_MS = 300

// Click-outside + Escape dismiss for popovers. Mirrors the pattern in
// ChatPanel.jsx so behaviour is consistent across the app.
function useClickOutside(ref, onOutside, enabled) {
  useEffect(() => {
    if (!enabled) return
    function handle(e) {
      if (ref.current && !ref.current.contains(e.target)) onOutside()
    }
    function escListener(e) { if (e.key === 'Escape') onOutside() }
    document.addEventListener('mousedown', handle)
    document.addEventListener('keydown', escListener)
    return () => {
      document.removeEventListener('mousedown', handle)
      document.removeEventListener('keydown', escListener)
    }
  }, [ref, onOutside, enabled])
}


// Long-press hook for touch devices. Returns pointer-event handlers that
// fire `onLongPress` after `delay` ms of continuous contact. Cancels on
// move or early release.
function useLongPress(onLongPress, delay = 500) {
  const timerRef = useRef(null)
  const cancel = useCallback(() => {
    if (timerRef.current) { clearTimeout(timerRef.current); timerRef.current = null }
  }, [])
  const onPointerDown = useCallback((e) => {
    if (e.pointerType !== 'touch') return
    timerRef.current = setTimeout(() => { onLongPress(e) }, delay)
  }, [onLongPress, delay])
  const onPointerUp = cancel
  const onPointerCancel = cancel
  const onPointerMove = cancel
  useEffect(() => cancel, [cancel])
  return { onPointerDown, onPointerUp, onPointerCancel, onPointerMove }
}
// ---------------------------------------------------------------------------
// Component.

export default function FeatureView({
  parsedFeature,            // current FeatureTree (from store.currentFeature)
  files,                    // file rows for the project (sketch picker)
  onChangeTree,             // (nextTree) => void
  loadSketchContent,        // (path: string) => Promise<string>; returns sketch JSON
}) {
  const tree = parsedFeature?.features || []
  const fileName = parsedFeature?.name || 'Feature'
  const currentFile = useWorkspace((s) => s.currentFile)
  const currentFileId = useWorkspace((s) => s.currentFileId)

  // Selection / pick mode lives in the workspace store so other UI (chat,
  // future tools) can read it. We wire two-way binding here.
  const featureSelection = useWorkspace((s) => s.featureSelection)
  const featurePickMode = useWorkspace((s) => s.featurePickMode)
  const featurePickTarget = useWorkspace((s) => s.featurePickTarget)
  const setFeatureSelection = useWorkspace((s) => s.setFeatureSelection)
  const setFeaturePickMode = useWorkspace((s) => s.setFeaturePickMode)
  const clearFeatureSelection = useWorkspace((s) => s.clearFeatureSelection)
  const createSketchOnFace = useWorkspace((s) => s.createSketchOnFace)
  const selectFile = useWorkspace((s) => s.selectFile)

  // Inspector drawer open state — on narrow viewports (< md) the inspector
  // slides in as an overlay; on ≥ md it is always visible as the right pane.
  const [inspectorOpen, setInspectorOpen] = useState(false)

  // Selected feature in the timeline (by id).
  const [selectedId, setSelectedId] = useState(null)
  useEffect(() => {
    if (!selectedId && tree.length > 0) setSelectedId(tree[tree.length - 1]?.id)
  }, [tree, selectedId])

  // Roving-tabindex index for the feature timeline (keyboard nav).
  // Points to the chip that currently owns tabIndex=0. Defaults to the last
  // chip (same as selectedId initialisation above). Clamped on tree change.
  const [rovingIdx, setRovingIdx] = useState(0)
  useEffect(() => {
    if (tree.length === 0) return
    setRovingIdx((prev) => Math.min(prev, tree.length - 1))
  }, [tree.length])

  // Ref to the timeline container so we can focus individual chips.
  const timelineRef = useRef(null)

  const handleTimelineKeyDown = useCallback((e) => {
    if (tree.length === 0) return
    let next = rovingIdx
    if (e.key === 'ArrowRight' || e.key === 'ArrowDown') {
      e.preventDefault()
      next = Math.min(rovingIdx + 1, tree.length - 1)
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowUp') {
      e.preventDefault()
      next = Math.max(rovingIdx - 1, 0)
    } else if (e.key === 'Home') {
      e.preventDefault()
      next = 0
    } else if (e.key === 'End') {
      e.preventDefault()
      next = tree.length - 1
    } else {
      return
    }
    setRovingIdx(next)
    // Move DOM focus to the newly-roving chip button.
    const chipBtns = timelineRef.current?.querySelectorAll('[data-chip-btn]')
    if (chipBtns?.[next]) chipBtns[next].focus()
  }, [rovingIdx, tree.length])

  // Cached evaluation results — survive across debounced re-runs so a brief
  // error doesn't wipe the viewport.
  const [meshes, setMeshes] = useState([])
  const [evalState, setEvalState] = useState({ loading: false, error: null, ms: null })
  const lastGoodMeshesRef = useRef([])

  const sketchCacheRef = useRef(new Map())
  useEffect(() => { sketchCacheRef.current = new Map() }, [files])

  // Track the structural fingerprint of the tree (op kinds + ids in order) so
  // we can clear selection only when topology actually changes — pure
  // parameter tweaks (e.g. tweaking a height) preserve face/edge ids and
  // keep selections valid.
  const lastStructuralKeyRef = useRef('')
  useEffect(() => {
    const key = tree.map((n) => `${n.op}:${n.id}`).join('|')
    if (key !== lastStructuralKeyRef.current) {
      if (lastStructuralKeyRef.current !== '') {
        // Avoid clearing on the very first render — only on subsequent edits.
        clearFeatureSelection()
      }
      lastStructuralKeyRef.current = key
    }
  }, [tree, clearFeatureSelection])

  // Debounced re-evaluation pipeline.
  const debounceRef = useRef(null)
  const seqRef = useRef(0)

  const triggerEvaluate = useCallback(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    const seq = ++seqRef.current
    debounceRef.current = setTimeout(async () => {
      const referenced = new Set()
      for (const node of tree) {
        if (node.sketch_path) referenced.add(node.sketch_path)
      }
      const sketches = {}
      for (const path of referenced) {
        try {
          if (sketchCacheRef.current.has(path)) {
            sketches[path] = sketchCacheRef.current.get(path)
            continue
          }
          const content = loadSketchContent
            ? await loadSketchContent(path)
            : null
          sketches[path] = content || ''
          sketchCacheRef.current.set(path, content || '')
        } catch (err) {
          sketches[path] = ''
        }
      }
      // For face-anchored sketches whose anchor is on the *current* feature
      // file, resolve the face's world frame before dispatch. We need a
      // partial evaluation up to the anchor feature node — the worker's
      // requestFaceOutline does that for us.
      for (const path of Object.keys(sketches)) {
        try {
          const obj = sketches[path] ? JSON.parse(sketches[path]) : null
          const plane = obj?.plane
          if (plane?.type === 'face' && plane.face_id != null && (plane.file_id == null || plane.file_id === currentFileId)) {
            // Slice the tree up to (and including) the anchor feature node so
            // the face id resolves against the body that produced it. If
            // feature_node_id is missing we just use the whole tree.
            let sliced = tree
            if (plane.feature_node_id) {
              const idx = tree.findIndex((n) => n.id === plane.feature_node_id)
              if (idx >= 0) sliced = tree.slice(0, idx + 1)
            }
            const result = await requestFaceOutline(sliced, sketches, plane.face_id)
            if (result && result.ok && result.frame) {
              const baked = { ...obj, plane: { ...plane, frame: result.frame } }
              sketches[path] = JSON.stringify(baked)
            }
          }
        } catch { /* tolerate */ }
      }
      setEvalState((s) => ({ ...s, loading: true, error: null }))
      const t0 = performance.now()
      const result = await runFeatures(tree, sketches)
      const ms = Math.round(performance.now() - t0)
      if (seq !== seqRef.current) return
      if (result.stale) return
      if (result.error) {
        setEvalState({ loading: false, error: result.error, ms })
        if (result.partial) {
          const fallback = [{ id: 'partial', mesh: result.partial }]
          setMeshes(fallback)
        }
        return
      }
      const next = (result.meshes || []).map((m, i) => ({
        id: m.id || `body-${i}`,
        mesh: m,
      }))
      lastGoodMeshesRef.current = next
      setMeshes(next)
      setEvalState({ loading: false, error: null, ms })
    }, DEBOUNCE_MS)
  }, [tree, loadSketchContent])

  useEffect(() => { prewarmOcct() }, [])

  useEffect(() => {
    triggerEvaluate()
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current) }
  }, [parsedFeature, triggerEvaluate])

  // ---- Tree mutations ----
  const updateTree = useCallback((mutator) => {
    const nextFeatures = mutator(tree)
    onChangeTree?.({
      ...parsedFeature,
      features: Array.isArray(nextFeatures) ? nextFeatures : [],
    })
  }, [tree, parsedFeature, onChangeTree])

  const addFeature = useCallback((op) => {
    const kind = KIND_BY_OP[op]
    if (!kind) return
    const id = newFeatureId(op)
    const node = { id, op, ...kind.defaults }
    if (['pocket', 'fillet', 'chamfer', 'shell', 'hole'].includes(op)) {
      const lastBody = [...tree].reverse().find((n) => n.op === 'pad' || n.op === 'revolve')
      if (lastBody) node.target_id = lastBody.id
    }
    updateTree((arr) => [...arr, node])
    setSelectedId(id)
  }, [tree, updateTree])

  const removeFeature = useCallback((id) => {
    updateTree((arr) => arr.filter((n) => n.id !== id))
    if (selectedId === id) setSelectedId(null)
  }, [updateTree, selectedId])

  const moveFeature = useCallback((id, dir) => {
    updateTree((arr) => {
      const idx = arr.findIndex((n) => n.id === id)
      if (idx < 0) return arr
      const j = dir === 'up' ? idx - 1 : idx + 1
      if (j < 0 || j >= arr.length) return arr
      const out = arr.slice()
      const tmp = out[idx]; out[idx] = out[j]; out[j] = tmp
      return out
    })
  }, [updateTree])

  const patchFeature = useCallback((id, patch) => {
    updateTree((arr) => arr.map((n) => n.id === id ? { ...n, ...patch } : n))
  }, [updateTree])

  // ---- Push/pull commit: append a push_pull feature node ----
  const onPushPullCommit = useCallback(({ partId, faceId, faceName, distance }) => {
    if (Math.abs(distance) < 0.05) return
    void partId
    const id = newFeatureId('push_pull')
    // T5: dual-write face_name (persistent) + face_id (legacy fallback).
    const node = { id, op: 'push_pull', face_id: faceId, distance }
    if (faceName) node.face_name = faceName
    updateTree((arr) => [...arr, node])
    setSelectedId(id)
    setFeaturePickMode(null)
  }, [updateTree, setFeaturePickMode])

  // ---- Sketch-on-face: handle a one-shot face pick that creates a sketch ----
  // T5: onFacePicked now receives { id, name, partId } from FeatureRenderer
  // (name is the persistent face name, id is the integer id).
  const onFacePicked = useCallback(async (pickArg, legacyPartId) => {
    // Support both legacy (faceId, partId) and new ({ id, name, partId }) shapes.
    let faceId, faceName, partId
    if (pickArg && typeof pickArg === 'object' && 'id' in pickArg) {
      faceId   = pickArg.id
      faceName = pickArg.name || ''
      partId   = pickArg.partId
    } else {
      faceId   = pickArg
      faceName = ''
      partId   = legacyPartId
    }
    void partId
    const mode = featurePickMode
    const target = featurePickTarget
    if (mode === 'sketch_on_face') {
      // Find the parent feature node that produced this body. v1 just uses
      // the latest pad/revolve as the anchor — multi-body trees aren't a v1
      // goal anyway.
      const anchor = [...tree].reverse().find((n) => n.op === 'pad' || n.op === 'revolve')
      const name = window.prompt('Sketch name', 'sketch-on-face.sketch')
      if (!name) {
        setFeaturePickMode(null)
        return
      }
      const created = await createSketchOnFace({
        parentId: currentFile?.parent_id || null,
        name: name.endsWith('.sketch') ? name : `${name}.sketch`,
        featureFileId: currentFileId,
        featureNodeId: anchor?.id || null,
        faceId,
      })
      setFeaturePickMode(null)
      if (created) await selectFile(created.id)
      return
    }
    if (mode === 'one_shot_face' && target) {
      // Fill the target field on the target feature with the picked face id.
      // T5: also dual-write the persistent name into a companion _name field
      // (e.g. target_face_id → target_face_name, face_id → face_name).
      if (target.accept === 'face_multi') {
        patchFeature(target.featureId, {
          [target.fieldKey]: Array.from(new Set([...(_arrayField(tree, target.featureId, target.fieldKey)), faceId])),
        })
      } else {
        const patch = { [target.fieldKey]: faceId }
        // Derive companion name key: target_face_id → target_face_name, face_id → face_name
        const nameKey = target.fieldKey.replace(/_id$/, '_name')
        if (faceName && nameKey !== target.fieldKey) patch[nameKey] = faceName
        patchFeature(target.featureId, patch)
      }
      setFeaturePickMode(null)
    }
    if (mode === 'one_shot_axis' || mode === 'one_shot_plane') {
      // Treat axis/plane picks: fill with the face id (numeric) for plane,
      // and reject for axis (the user should pick an edge for axis).
      if (mode === 'one_shot_plane' && target) {
        const patch = { [target.fieldKey]: faceId }
        // T6: dual-write plane_face_name when picking a face as the mirror plane.
        if (faceName && target.fieldKey === 'plane') patch.plane_face_name = faceName
        patchFeature(target.featureId, patch)
        setFeaturePickMode(null)
      }
    }
  }, [featurePickMode, featurePickTarget, tree, createSketchOnFace, currentFile, currentFileId, patchFeature, setFeaturePickMode, selectFile])

  // ---- Watch selection updates: if the active inspector has a one-shot pick
  // armed for an edge or edge_multi field, write the picked id back. ----
  useEffect(() => {
    if (!featurePickMode || !featurePickTarget) return
    if (featurePickMode === 'one_shot_edge') {
      // Take the most recently added edge id from the selection set.
      const list = Array.from(featureSelection.edgeIds || []).map((k) => Number(k.split('|')[1]))
      if (list.length === 0) return
      const newest = list[list.length - 1]
      const t = featurePickTarget
      if (t.accept === 'edge_multi') {
        patchFeature(t.featureId, (prev) => prev) // noop, we update via callback
        const nodeIdx = tree.findIndex((n) => n.id === t.featureId)
        if (nodeIdx >= 0) {
          const cur = tree[nodeIdx]
          const ids = Array.isArray(cur.edge_ids) ? cur.edge_ids : []
          if (!ids.includes(newest)) {
            patchFeature(t.featureId, { edge_ids: [...ids, newest], edge_filter: 'manual' })
          }
        }
      } else {
        patchFeature(t.featureId, { [t.fieldKey]: newest })
      }
      setFeaturePickMode(null)
    }
    if (featurePickMode === 'one_shot_axis') {
      const list = Array.from(featureSelection.edgeIds || []).map((k) => Number(k.split('|')[1]))
      if (list.length === 0) return
      const newest = list[list.length - 1]
      patchFeature(featurePickTarget.featureId, { [featurePickTarget.fieldKey]: newest })
      setFeaturePickMode(null)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [featureSelection])

  // ---- Auto-sync selection → active feature's edge/face fields when in
  //      multi-pick (face / edge) mode. ----
  useEffect(() => {
    if (featurePickMode !== 'edge' && featurePickMode !== 'face') return
    const active = tree.find((n) => n.id === selectedId)
    if (!active) return
    if (featurePickMode === 'edge' && (active.op === 'fillet' || active.op === 'chamfer')) {
      const ids = Array.from(featureSelection.edgeIds || []).map((k) => Number(k.split('|')[1]))
      // Only update if the array actually changed.
      const cur = Array.isArray(active.edge_ids) ? active.edge_ids : []
      if (cur.length !== ids.length || cur.some((v, i) => v !== ids[i])) {
        patchFeature(active.id, { edge_ids: ids, edge_filter: 'manual' })
      }
    } else if (featurePickMode === 'face' && active.op === 'shell') {
      const ids = Array.from(featureSelection.faceIds || []).map((k) => Number(k.split('|')[1]))
      const cur = Array.isArray(active.face_ids) ? active.face_ids : []
      if (cur.length !== ids.length || cur.some((v, i) => v !== ids[i])) {
        patchFeature(active.id, { face_ids: ids })
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [featureSelection, featurePickMode, selectedId])

  // ---- Derived UI state ----
  const sketchFiles = useMemo(() => {
    return (files || []).filter((f) => {
      if (!f) return false
      if (f.kind === 'sketch') return true
      const n = (f.name || '').toLowerCase()
      return n.endsWith('.sketch')
    })
  }, [files])

  const sketchPaths = useMemo(() => {
    const byId = new Map((files || []).map((f) => [f.id, f]))
    function pathOf(f) {
      const parts = []
      let cur = f
      let safety = 0
      while (cur && safety++ < 64) {
        parts.unshift(cur.name)
        if (!cur.parent_id) break
        cur = byId.get(cur.parent_id)
      }
      return '/' + parts.join('/')
    }
    return sketchFiles.map((f) => ({ id: f.id, path: pathOf(f), name: f.name }))
  }, [files, sketchFiles])

  const selectedFeature = useMemo(
    () => tree.find((n) => n.id === selectedId) || null,
    [tree, selectedId],
  )

  const vertexCount = useMemo(() => {
    let n = 0
    for (const m of meshes) {
      const v = m?.mesh?.vertices
      if (v) n += v.length / 3
    }
    return n
  }, [meshes])

  // ---- Render ----
  const selCount = featureSelection.faceIds.size + featureSelection.edgeIds.size
  return (
    <div className="flex-1 min-h-0 flex flex-col bg-ink-950 text-ink-100">
      {/* Unified toolbar — add-feature popover + file name + timeline chips
          on the left; pick-mode controls + inspector toggle on the right. */}
      <div className="border-b border-ink-800 bg-ink-900 px-3 h-11 flex items-center gap-2">
        <AddFeaturePopover onPick={(op) => addFeature(op)} />

        <span className="w-px h-5 bg-ink-800 mx-0.5 flex-shrink-0" aria-hidden="true" />

        <span
          className="text-xs text-ink-400 truncate max-w-[120px] sm:max-w-[160px] flex-shrink-0"
          title={fileName}
        >
          {fileName}
        </span>

        {/* Timeline — scroll horizontally if it gets long.
            role="tree" + role="treeitem" for a11y even though it is a flat
            timeline (aria-level="1" throughout).
            Keyboard: ArrowLeft/Right move between chips (roving tabindex). */}
        <div
          ref={timelineRef}
          role="tree"
          aria-label="Feature timeline"
          className="flex-1 min-w-0 flex items-center gap-1 overflow-x-auto scrollbar-thin"
          title={tree.length > 1 ? 'Selections may reset after structural changes.' : undefined}
          onKeyDown={handleTimelineKeyDown}
        >
          {tree.length === 0 ? (
            <span className="text-xs text-ink-500 italic">
              No features yet — click <span className="text-ink-300">Add feature</span> to start.
            </span>
          ) : (
            tree.map((node, idx) => {
              const kind = KIND_BY_OP[node.op]
              const Icon = kind?.icon || Box
              const isSel = node.id === selectedId
              return (
                <FeatureTimelineChip
                  key={node.id}
                  node={node}
                  kind={kind}
                  Icon={Icon}
                  idx={idx}
                  isSel={isSel}
                  rovingTabIndex={idx === rovingIdx ? 0 : -1}
                  onSelect={() => { setSelectedId(node.id); setRovingIdx(idx); setInspectorOpen(true) }}
                  onDelete={() => { if (confirm(`Delete ${kind?.label || node.op} '${node.id}'?`)) removeFeature(node.id) }}
                />
              )
            })
          )}
        </div>

        {/* Pick-mode controls (right side). */}
        <div className="flex items-center gap-1 flex-shrink-0">
          <ModeBtn
            active={featurePickMode === 'face'}
            onClick={() => setFeaturePickMode(featurePickMode === 'face' ? null : 'face')}
            icon={Pointer}
            label="Faces"
            title="Click faces to select. Shift-click to add. Drives Shell/face_ids of the active feature."
          />
          <ModeBtn
            active={featurePickMode === 'edge'}
            onClick={() => setFeaturePickMode(featurePickMode === 'edge' ? null : 'edge')}
            icon={Pointer}
            label="Edges"
            title="Click edges to select. Shift-click to add. Drives Fillet/Chamfer manual edge_ids."
          />
          <span className="w-px h-5 bg-ink-800 mx-1" aria-hidden="true" />
          <ModeBtn
            active={featurePickMode === 'pushpull'}
            onClick={() => setFeaturePickMode(featurePickMode === 'pushpull' ? null : 'pushpull')}
            icon={Move}
            label="Push/Pull"
            title="Drag a face along its normal. Release to commit a Pad/Pocket."
          />
          <ModeBtn
            active={featurePickMode === 'sketch_on_face'}
            onClick={() => setFeaturePickMode(featurePickMode === 'sketch_on_face' ? null : 'sketch_on_face')}
            icon={PencilLine}
            label="Sketch on face"
            title="Click a planar face to create a new sketch on it."
          />
          {/* Inspector toggle — only visible on narrow viewports (< md). */}
          <button
            type="button"
            onClick={() => setInspectorOpen((v) => !v)}
            aria-label={inspectorOpen ? 'Close inspector' : 'Open inspector'}
            aria-expanded={inspectorOpen}
            aria-controls="feature-inspector-panel"
            className={`md:hidden inline-flex items-center justify-center w-7 h-7 rounded-md border text-xs transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60
              ${inspectorOpen
                ? 'border-kerf-300/60 bg-kerf-300/15 text-kerf-100'
                : 'border-ink-700 bg-transparent text-ink-300 hover:bg-ink-800'}`}
          >
            <SlidersHorizontal size={13} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Main: viewport + inspector.
          ≥ md: side-by-side grid (1fr 280px), inspector always visible.
          < md: stacked; inspector is an off-canvas overlay anchored to the
                bottom (slides up, covers ~60% of height). */}
      <div className="flex-1 min-h-0 relative md:grid" style={{ gridTemplateColumns: '1fr 280px' }}>
        <main className="relative min-h-0 min-w-0 h-full">
          <FeatureRenderer
            meshes={meshes}
            selection={featureSelection}
            pickMode={featurePickMode}
            onSelectionChange={setFeatureSelection}
            onFacePick={onFacePicked}
            onPushPullCommit={onPushPullCommit}
            className="w-full h-full"
          />
          {evalState.loading && (
            <div className="absolute top-3 left-3 inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-ink-900/85 backdrop-blur border border-ink-700 text-[11px] text-ink-200 shadow-lg shadow-black/30">
              <Loader2 size={11} className="animate-spin text-kerf-300" aria-hidden="true" />
              <span>Evaluating</span>
            </div>
          )}
          {featurePickMode && (
            <div className="absolute top-3 right-3 inline-flex items-center gap-1.5 pl-2 pr-1 py-1 rounded-md bg-kerf-300/15 backdrop-blur border border-kerf-300/40 text-[11px] text-kerf-100 shadow-lg shadow-black/30">
              <Crosshair size={11} aria-hidden="true" />
              <span>
                {featurePickMode === 'pushpull' && 'Push/Pull · drag a face'}
                {featurePickMode === 'sketch_on_face' && 'Click a planar face'}
                {featurePickMode === 'face' && 'Click faces · shift to add'}
                {featurePickMode === 'edge' && 'Click edges · shift to add'}
                {featurePickMode === 'one_shot_face' && 'Pick a face'}
                {featurePickMode === 'one_shot_edge' && 'Pick an edge'}
                {featurePickMode === 'one_shot_axis' && 'Pick an edge for axis'}
                {featurePickMode === 'one_shot_plane' && 'Pick a face for plane'}
              </span>
              <button
                type="button"
                onClick={() => setFeaturePickMode(null)}
                aria-label="Cancel pick mode"
                className="ml-0.5 inline-flex items-center justify-center w-4 h-4 rounded text-kerf-200 hover:text-white hover:bg-kerf-300/20 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60"
                title="Cancel pick"
              >
                <X size={10} aria-hidden="true" />
              </button>
            </div>
          )}
        </main>

        {/* Right: inspector — always visible at ≥ md; drawer overlay at < md. */}
        {/* Backdrop for the mobile drawer */}
        {inspectorOpen && (
          <div
            className="md:hidden fixed inset-0 z-30 bg-black/40"
            aria-hidden="true"
            onClick={() => setInspectorOpen(false)}
          />
        )}
        <aside
          id="feature-inspector-panel"
          aria-label="Feature inspector"
          className={`
            md:border-l md:border-ink-800 md:bg-ink-900/60 md:min-h-0 md:overflow-y-auto md:static md:translate-y-0 md:z-auto md:block md:shadow-none
            fixed bottom-0 left-0 right-0 z-40 max-h-[65vh] overflow-y-auto rounded-t-xl border-t border-ink-700 bg-ink-900 shadow-2xl shadow-black/60 transition-transform duration-200
            ${inspectorOpen ? 'translate-y-0' : 'translate-y-full md:translate-y-0'}
          `}
        >
          {/* Mobile handle — tap to close */}
          <button
            type="button"
            className="md:hidden flex justify-center py-2 w-full focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60 rounded-t-xl"
            onClick={() => setInspectorOpen(false)}
            aria-label="Close inspector"
          >
            <span className="w-8 h-1 rounded-full bg-ink-600" aria-hidden="true" />
          </button>
          {!selectedFeature ? (
            <div className="p-4 text-xs text-ink-500 italic">
              Select a feature in the timeline to edit its parameters.
            </div>
          ) : (
            <FeatureInspector
              feature={selectedFeature}
              tree={tree}
              sketchPaths={sketchPaths}
              selection={featureSelection}
              pickMode={featurePickMode}
              setFeaturePickMode={setFeaturePickMode}
              setFeatureSelection={setFeatureSelection}
              onPatch={(patch) => patchFeature(selectedFeature.id, patch)}
              onMoveUp={() => moveFeature(selectedFeature.id, 'up')}
              onMoveDown={() => moveFeature(selectedFeature.id, 'down')}
              onDelete={() => removeFeature(selectedFeature.id)}
            />
          )}
        </aside>
      </div>

      {/* Bottom: status bar — eval/error left, selection summary middle,
          re-evaluate right. */}
      <div className="flex items-center gap-3 px-3 h-7 border-t border-ink-800 bg-ink-900 text-[11px] font-mono text-ink-500 flex-shrink-0">
        {evalState.error ? (
          <span className="inline-flex items-center gap-1.5 text-red-400 min-w-0">
            <AlertTriangle size={11} className="flex-shrink-0" aria-hidden="true" />
            <span className="truncate" title={evalState.error}>{evalState.error}</span>
          </span>
        ) : (
          <span className="inline-flex items-center gap-1.5">
            <span className="text-ink-300">{vertexCount.toLocaleString()}</span>
            <span className="text-ink-500">vertices</span>
            <span className="text-ink-700" aria-hidden="true">·</span>
            <span className="text-ink-300">{meshes.length}</span>
            <span className="text-ink-500">{meshes.length === 1 ? 'body' : 'bodies'}</span>
            {evalState.ms != null && (
              <>
                <span className="text-ink-700" aria-hidden="true">·</span>
                <span>{evalState.ms}ms</span>
              </>
            )}
          </span>
        )}
        <div className="flex-1" />
        {selCount > 0 && (
          <>
            <span className="inline-flex items-center gap-1.5">
              <span className="text-ink-500">Sel</span>
              <span className="text-ink-300">{featureSelection.faceIds.size}</span>
              <span className="text-ink-500">{featureSelection.faceIds.size === 1 ? 'face' : 'faces'}</span>
              <span className="text-ink-700" aria-hidden="true">·</span>
              <span className="text-ink-300">{featureSelection.edgeIds.size}</span>
              <span className="text-ink-500">{featureSelection.edgeIds.size === 1 ? 'edge' : 'edges'}</span>
            </span>
            <button
              type="button"
              onClick={() => clearFeatureSelection()}
              aria-label="Clear viewport selection"
              className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-ink-400 hover:text-kerf-300 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60"
              title="Clear viewport selection"
            >
              clear
            </button>
            <span className="w-px h-4 bg-ink-800" aria-hidden="true" />
          </>
        )}
        <button
          type="button"
          onClick={() => triggerEvaluate()}
          aria-label="Force re-evaluation"
          className="inline-flex items-center gap-1 px-2 py-0.5 rounded text-ink-300 hover:text-kerf-300 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60"
          title="Force re-evaluation"
        >
          <Play size={10} aria-hidden="true" />
          <span>Re-evaluate</span>
        </button>
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// FeatureTimelineChip — a single chip in the horizontal timeline. Handles
// pointer-unified interactions:
//   - pointer (mouse/stylus): hover shows X delete button; right-click deletes.
//   - touch: long-press opens a small dot-menu (⋯) popover with Delete.
//   - keyboard: Enter/Space selects; Delete key deletes.

function FeatureTimelineChip({ node, kind, Icon, idx, isSel, rovingTabIndex = 0, onSelect, onDelete }) {
  const [dotMenuOpen, setDotMenuOpen] = useState(false)
  const wrapRef = useRef(null)
  useClickOutside(wrapRef, () => setDotMenuOpen(false), dotMenuOpen)
  const longPress = useLongPress(useCallback(() => setDotMenuOpen(true), []))

  const label = kind?.label || node.op

  function handleKeyDown(e) {
    // Enter/Space selects. Delete removes. Arrow keys bubble up to the
    // tree container's roving-tabindex handler.
    if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect() }
    if (e.key === 'Delete') onDelete()
  }

  return (
    <div ref={wrapRef} role="treeitem" aria-selected={isSel} aria-level={1} className="flex items-center gap-1 flex-shrink-0 relative">
      {idx > 0 && <ChevronRight size={11} className="text-ink-600" aria-hidden="true" />}
      <button
        type="button"
        data-chip-btn=""
        tabIndex={rovingTabIndex}
        onClick={onSelect}
        onKeyDown={handleKeyDown}
        onContextMenu={(ev) => { ev.preventDefault(); onDelete() }}
        {...longPress}
        aria-label={`${label}, feature ${idx + 1}${isSel ? ', selected' : ''}`}
        className={`group relative inline-flex items-center gap-1.5 pl-1.5 pr-2 py-1 rounded-md border text-xs transition-colors
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60
          ${isSel
            ? 'border-kerf-300/60 bg-kerf-300/10 text-kerf-100 shadow-[0_0_0_1px_rgba(255,214,51,0.15)]'
            : 'border-ink-800 bg-ink-850 text-ink-200 hover:border-ink-600 hover:bg-ink-800'}`}
        title={`${label} · right-click or long-press to delete`}
      >
        <span
          aria-hidden="true"
          className={`inline-flex items-center justify-center w-4 h-4 rounded text-[10px] font-mono leading-none flex-shrink-0
            ${isSel ? 'bg-kerf-300/30 text-kerf-100' : 'bg-ink-800 text-ink-400'}`}
        >
          {idx + 1}
        </span>
        <Icon size={12} aria-hidden="true" className={isSel ? 'text-kerf-200' : 'text-ink-300'} />
        {/* Label truncates at narrow viewport */}
        <span className="truncate max-w-[6rem] sm:max-w-[8rem]">{label}</span>
        {/* Desktop: show X delete button when selected */}
        {isSel && (
          <button
            type="button"
            aria-label={`Delete ${label}`}
            onClick={(ev) => { ev.stopPropagation(); onDelete() }}
            className="ml-0.5 -mr-0.5 inline-flex items-center justify-center w-4 h-4 rounded text-ink-400 hover:text-red-300 hover:bg-red-900/30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60"
          >
            <X size={10} aria-hidden="true" />
          </button>
        )}
      </button>
      {/* Dot-menu — always accessible; on touch long-press opens it automatically. */}
      <button
        type="button"
        aria-label={`Actions for ${label}`}
        aria-expanded={dotMenuOpen}
        aria-haspopup="menu"
        onClick={(e) => { e.stopPropagation(); setDotMenuOpen((v) => !v) }}
        className={`inline-flex items-center justify-center w-5 h-5 rounded text-ink-500 hover:text-ink-200 hover:bg-ink-700 transition-colors flex-shrink-0
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60
          ${dotMenuOpen ? 'text-ink-200 bg-ink-700' : ''}`}
        title="Feature actions"
      >
        <MoreHorizontal size={12} aria-hidden="true" />
      </button>
      {dotMenuOpen && (
        <div
          role="menu"
          className="absolute top-full left-0 mt-1 z-50 min-w-[130px] rounded-md border border-ink-700 bg-ink-900 shadow-xl shadow-black/50 py-0.5"
        >
          <button
            role="menuitem"
            type="button"
            onClick={() => { setDotMenuOpen(false); onDelete() }}
            className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-red-300 hover:bg-red-900/25 focus-visible:outline-none focus-visible:bg-red-900/25"
          >
            <Trash2 size={11} aria-hidden="true" />
            Delete feature
          </button>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Add-feature popover. Single button replaces the 14-icon kitchen-sink; opens
// a panel with FEATURE_CATEGORIES groups and a 3-column grid of icon tiles.
//
// Keyboard:
//   Enter/Space on trigger  → open + focus first item
//   Arrow keys              → move through items (3-col grid: Left/Right wrap
//                             within row; Up/Down move by column)
//   Escape                  → close + return focus to trigger
//   Enter/Space on item     → pick + close + return focus to trigger

function AddFeaturePopover({ onPick }) {
  const [open, setOpen] = useState(false)
  const wrapRef = useRef(null)
  const triggerRef = useRef(null)
  const menuRef = useRef(null)
  useClickOutside(wrapRef, () => setOpen(false), open)

  // Flatten all valid ops across categories for sequential focus.
  const allOps = useMemo(
    () => FEATURE_CATEGORIES.flatMap((cat) => cat.ops.filter((op) => KIND_BY_OP[op])),
    [],
  )
  const COLS = 3

  const closeAndReturnFocus = useCallback(() => {
    setOpen(false)
    // Defer so the menu has unmounted before we attempt focus.
    requestAnimationFrame(() => triggerRef.current?.focus())
  }, [])

  // When the popover opens, focus the first menu item.
  useEffect(() => {
    if (!open) return
    requestAnimationFrame(() => {
      const first = menuRef.current?.querySelector('[role="menuitem"]')
      first?.focus()
    })
  }, [open])

  function handleMenuKeyDown(e) {
    const items = Array.from(menuRef.current?.querySelectorAll('[role="menuitem"]') ?? [])
    if (!items.length) return
    const focused = document.activeElement
    const idx = items.indexOf(focused)

    if (e.key === 'Escape') {
      e.preventDefault()
      closeAndReturnFocus()
    } else if (e.key === 'ArrowRight') {
      e.preventDefault()
      const next = (idx + 1) % items.length
      items[next]?.focus()
    } else if (e.key === 'ArrowLeft') {
      e.preventDefault()
      const next = (idx - 1 + items.length) % items.length
      items[next]?.focus()
    } else if (e.key === 'ArrowDown') {
      e.preventDefault()
      const next = Math.min(idx + COLS, items.length - 1)
      items[next]?.focus()
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      const next = Math.max(idx - COLS, 0)
      items[next]?.focus()
    } else if (e.key === 'Home') {
      e.preventDefault()
      items[0]?.focus()
    } else if (e.key === 'End') {
      e.preventDefault()
      items[items.length - 1]?.focus()
    } else if (e.key === 'Tab') {
      // Trap focus: cycle within menu or close on Shift+Tab from first.
      if (e.shiftKey && idx === 0) {
        e.preventDefault()
        closeAndReturnFocus()
      } else if (!e.shiftKey && idx === items.length - 1) {
        e.preventDefault()
        items[0]?.focus()
      }
    }
  }

  return (
    <div ref={wrapRef} className="relative flex-shrink-0">
      <button
        ref={triggerRef}
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-label="Add feature to timeline"
        aria-expanded={open}
        aria-haspopup="menu"
        className={`inline-flex items-center gap-1.5 pl-2 pr-2.5 py-1.5 rounded-md border text-xs font-medium transition-colors
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60
          ${open
            ? 'border-kerf-300/60 bg-kerf-300/15 text-kerf-100'
            : 'border-ink-700 bg-ink-850 text-ink-100 hover:bg-ink-800 hover:border-ink-600'}`}
        title="Add a feature to the timeline"
      >
        <Plus size={13} aria-hidden="true" className={open ? 'text-kerf-200' : 'text-kerf-300'} />
        <span>Add feature</span>
        <ChevronDown
          size={11}
          aria-hidden="true"
          className={`text-ink-400 transition-transform ${open ? 'rotate-180' : ''}`}
        />
      </button>

      {open && (
        <div
          ref={menuRef}
          className="absolute top-full left-0 mt-1.5 z-30 w-[min(420px,calc(100vw-2rem))] rounded-lg border border-ink-700 bg-ink-900 shadow-2xl shadow-black/60 overflow-hidden"
          role="menu"
          aria-label="Add feature"
          onKeyDown={handleMenuKeyDown}
        >
          <div className="max-h-[70vh] overflow-y-auto py-1.5">
            {FEATURE_CATEGORIES.map((cat, ci) => (
              <div key={cat.id} className={ci > 0 ? 'border-t border-ink-800 mt-1.5 pt-1.5' : ''}>
                <div className="px-3 pt-1.5 pb-1 text-[10px] uppercase tracking-wider text-ink-500 font-medium">
                  {cat.label}
                </div>
                <div className="grid grid-cols-3 gap-0.5 px-1.5 pb-1.5">
                  {cat.ops.map((op) => {
                    const k = KIND_BY_OP[op]
                    if (!k) return null
                    const Icon = k.icon
                    return (
                      <button
                        key={op}
                        type="button"
                        role="menuitem"
                        tabIndex={-1}
                        onClick={() => { onPick(op); closeAndReturnFocus() }}
                        aria-label={`Add ${k.label}`}
                        className="group flex flex-col items-center gap-1 px-2 py-2.5 rounded-md text-ink-200 hover:bg-ink-800 hover:text-kerf-200 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60"
                        title={`Add ${k.label}`}
                      >
                        <Icon size={18} aria-hidden="true" className="text-ink-300 group-hover:text-kerf-300" />
                        <span className="text-[11px] leading-none">{k.label}</span>
                      </button>
                    )
                  })}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Right-pane inspector. Renders the field schema for the feature's op.

function FeatureInspector({
  feature,
  tree,
  sketchPaths,
  selection,
  pickMode,
  setFeaturePickMode,
  setFeatureSelection,
  onPatch,
  onMoveUp,
  onMoveDown,
  onDelete,
}) {
  const kind = KIND_BY_OP[feature.op]
  const bodyFeatures = useMemo(() => {
    const idx = tree.findIndex((n) => n.id === feature.id)
    if (idx < 0) return []
    return tree.slice(0, idx).filter((n) => n.op === 'pad' || n.op === 'revolve' || n.op === 'pocket' || n.op === 'fillet' || n.op === 'chamfer' || n.op === 'shell' || n.op === 'hole' || n.op === 'push_pull' || n.op === 'linear_pattern' || n.op === 'polar_pattern' || n.op === 'mirror_pattern')
  }, [tree, feature.id])

  if (!kind) {
    return (
      <div className="p-4 text-xs text-ink-500 italic">
        Unknown op: {feature.op}
      </div>
    )
  }
  const Icon = kind.icon

  // Shared input/select classes — h-8 px-2 text-sm matches Editor.jsx baseline.
  const inputCls = 'w-full h-8 px-2 text-sm bg-ink-900 border border-ink-800 rounded ' +
    'focus:outline-none focus:border-kerf-300/50 focus-visible:ring-2 focus-visible:ring-kerf-300/40 ' +
    'text-ink-100 font-mono'
  const selectCls = 'w-full h-8 px-2 text-sm bg-ink-900 border border-ink-800 rounded ' +
    'focus:outline-none focus:border-kerf-300/50 focus-visible:ring-2 focus-visible:ring-kerf-300/40 ' +
    'text-ink-100'

  return (
    <div className="flex flex-col">
      {/* Header — feature name + reorder + delete. */}
      <div className="sticky top-0 z-10 px-3 py-2.5 bg-ink-900 border-b border-ink-800 flex items-center gap-2">
        <span className="inline-flex items-center justify-center w-6 h-6 rounded bg-kerf-300/15 border border-kerf-300/30 flex-shrink-0" aria-hidden="true">
          <Icon size={13} className="text-kerf-200" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm font-medium text-ink-100 leading-tight">{kind.label}</div>
          <div className="text-[10px] text-ink-500 font-mono truncate" title={feature.id}>
            {feature.id}
          </div>
        </div>
        <div className="flex items-center gap-0.5 flex-shrink-0" role="group" aria-label="Feature actions">
          <button
            type="button"
            onClick={onMoveUp}
            aria-label="Move feature up in timeline"
            className="inline-flex items-center justify-center w-6 h-6 rounded text-ink-400 hover:text-kerf-300 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60"
            title="Move up in timeline"
          >
            <ChevronUp size={13} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={onMoveDown}
            aria-label="Move feature down in timeline"
            className="inline-flex items-center justify-center w-6 h-6 rounded text-ink-400 hover:text-kerf-300 hover:bg-ink-800 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60"
            title="Move down in timeline"
          >
            <ChevronDown size={13} aria-hidden="true" />
          </button>
          <button
            type="button"
            onClick={onDelete}
            aria-label={`Delete ${kind.label} feature`}
            className="inline-flex items-center justify-center w-6 h-6 rounded text-ink-400 hover:text-red-300 hover:bg-red-900/25 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60"
            title="Delete this feature"
          >
            <Trash2 size={12} aria-hidden="true" />
          </button>
        </div>
      </div>

      {/* Body — field list. */}
      <div className="px-3 py-3 space-y-3">
      {kind.fields.map((field) => {
        if (field.showWhen && !field.showWhen(feature)) return null
        const fieldId = `inspector-${feature.id}-${field.key}`
        const complexKinds = ['edge_picker','face_picker','face_picker_single','axis_picker','plane_picker','sketch_path_list','edge_radius_list']
        return (
          <div key={field.key} className="space-y-1.5">
            <label
              htmlFor={complexKinds.includes(field.kind) ? undefined : fieldId}
              className="block text-[11px] font-medium text-ink-300"
            >
              {field.label}
            </label>
            {field.kind === 'number' && (
              <input
                id={fieldId}
                type="number"
                value={feature[field.key] ?? ''}
                onChange={(ev) => {
                  const v = ev.target.value === '' ? '' : Number(ev.target.value)
                  onPatch({ [field.key]: v })
                }}
                min={field.min}
                max={field.max}
                step={field.step ?? 'any'}
                aria-label={field.label}
                className={inputCls}
              />
            )}
            {field.kind === 'text' && (
              <input
                id={fieldId}
                type="text"
                value={feature[field.key] ?? ''}
                onChange={(ev) => onPatch({ [field.key]: ev.target.value })}
                aria-label={field.label}
                className={inputCls}
              />
            )}
            {field.kind === 'select' && (
              <select
                id={fieldId}
                value={feature[field.key] ?? field.options?.[0]?.value}
                onChange={(ev) => onPatch({ [field.key]: ev.target.value })}
                aria-label={field.label}
                className={selectCls}
              >
                {(field.options || []).map((o) => (
                  <option key={o.value} value={o.value}>{o.label}</option>
                ))}
              </select>
            )}
            {field.kind === 'sketch_picker' && (
              <select
                id={fieldId}
                value={feature[field.key] ?? ''}
                onChange={(ev) => onPatch({ [field.key]: ev.target.value })}
                aria-label={field.label}
                className={selectCls + ' font-mono'}
              >
                <option value="">— pick a sketch —</option>
                {sketchPaths.map((s) => (
                  <option key={s.id} value={s.path}>{s.path}</option>
                ))}
              </select>
            )}
            {field.kind === 'feature_picker' && (
              <select
                id={fieldId}
                value={feature[field.key] ?? ''}
                onChange={(ev) => onPatch({ [field.key]: ev.target.value })}
                aria-label={field.label}
                className={selectCls + ' font-mono'}
              >
                <option value="">— pick a feature —</option>
                {bodyFeatures.map((n) => (
                  <option key={n.id} value={n.id}>{n.id} ({n.op})</option>
                ))}
              </select>
            )}
            {field.kind === 'edge_picker' && (
              <EdgeIdsField
                value={feature[field.key] || []}
                onChange={(ids) => onPatch({ [field.key]: ids, edge_filter: 'manual' })}
                pickArmed={pickMode === 'edge'}
                onArmPick={() => setFeaturePickMode(pickMode === 'edge' ? null : 'edge')}
                selection={selection}
                setSelection={setFeatureSelection}
              />
            )}
            {field.kind === 'face_picker' && (
              <FaceIdsField
                value={feature[field.key] || []}
                onChange={(ids) => onPatch({ [field.key]: ids })}
                pickArmed={pickMode === 'face'}
                onArmPick={() => setFeaturePickMode(pickMode === 'face' ? null : 'face')}
                selection={selection}
                setSelection={setFeatureSelection}
              />
            )}
            {field.kind === 'face_picker_single' && (
              <SingleFaceIdField
                value={feature[field.key]}
                onChange={(id) => onPatch({ [field.key]: id })}
                onArmPick={() => setFeaturePickMode('one_shot_face', { featureId: feature.id, fieldKey: field.key, accept: 'face' })}
              />
            )}
            {field.kind === 'axis_picker' && (
              <AxisField
                value={feature[field.key]}
                onChange={(v) => onPatch({ [field.key]: v })}
                onArmPick={() => setFeaturePickMode('one_shot_axis', { featureId: feature.id, fieldKey: field.key, accept: 'edge' })}
              />
            )}
            {field.kind === 'plane_picker' && (
              <PlaneField
                value={feature[field.key]}
                onChange={(v) => onPatch({ [field.key]: v })}
                onArmPick={() => setFeaturePickMode('one_shot_plane', { featureId: feature.id, fieldKey: field.key, accept: 'face' })}
              />
            )}
            {(field.kind === 'bool' || field.kind === 'boolean') && (
              <label className="flex items-center gap-2 h-8 px-2 bg-ink-900 border border-ink-800 rounded text-sm cursor-pointer hover:border-ink-700">
                <input
                  type="checkbox"
                  id={fieldId}
                  checked={feature[field.key] === true}
                  onChange={(ev) => onPatch({ [field.key]: ev.target.checked })}
                  className="w-3.5 h-3.5 accent-kerf-300"
                  aria-label={field.label}
                />
                <span className="text-ink-300 text-sm">{feature[field.key] === true ? 'on' : 'off'}</span>
              </label>
            )}
            {field.kind === 'sketch_path_list' && (
              <SketchPathListField
                value={feature[field.key] || []}
                onChange={(v) => onPatch({ [field.key]: v })}
                sketchPaths={sketchPaths}
              />
            )}
            {field.kind === 'edge_radius_list' && (
              <EdgeRadiusListField
                value={feature[field.key] || []}
                onChange={(v) => onPatch({ [field.key]: v })}
                pickArmed={pickMode === 'edge'}
                onArmPick={() => setFeaturePickMode(pickMode === 'edge' ? null : 'edge')}
                selection={selection}
                setSelection={setFeatureSelection}
              />
            )}
          </div>
        )
      })}
      {/* Caption — optional explanatory note for ops that benefit from one (e.g. surface_boolean). */}
      {kind.caption && (
        <div className="mx-3 mb-3 px-2 py-2 rounded bg-ink-800/60 border border-ink-700/50 text-[10px] text-ink-400 leading-relaxed">
          {kind.caption}
        </div>
      )}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Selection-driven field components.

// SketchPathListField — ordered list of sketch paths (loft profiles, etc.).
// Add via the dropdown at the bottom; remove via the X on each row; reorder
// with the up/down arrows.
function SketchPathListField({ value, onChange, sketchPaths }) {
  const list = Array.isArray(value) ? value : []
  const remaining = sketchPaths.filter((s) => !list.includes(s.path))
  return (
    <div className="space-y-1">
      {list.length === 0 ? (
        <div className="text-[11px] text-ink-500 italic">No profiles yet — pick at least 2.</div>
      ) : (
        <div className="space-y-0.5">
          {list.map((p, i) => (
            <div key={`${p}-${i}`} className="flex items-center gap-1 px-1.5 py-1 bg-ink-900 border border-ink-800 rounded text-xs font-mono">
              <span className="text-ink-500 w-4 text-right flex-shrink-0">{i + 1}.</span>
              <span className="flex-1 truncate text-ink-200 min-w-0">{p}</span>
              <button type="button" disabled={i === 0}
                aria-label="Move profile up"
                className="text-ink-500 hover:text-kerf-300 disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60 flex-shrink-0"
                onClick={() => {
                  const next = [...list]; ;[next[i - 1], next[i]] = [next[i], next[i - 1]]; onChange(next)
                }}>
                <ChevronUp size={12} aria-hidden="true" />
              </button>
              <button type="button" disabled={i === list.length - 1}
                aria-label="Move profile down"
                className="text-ink-500 hover:text-kerf-300 disabled:opacity-30 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60 flex-shrink-0"
                onClick={() => {
                  const next = [...list]; ;[next[i + 1], next[i]] = [next[i], next[i + 1]]; onChange(next)
                }}>
                <ChevronDown size={12} aria-hidden="true" />
              </button>
              <button type="button"
                aria-label={`Remove profile ${p}`}
                className="text-ink-500 hover:text-red-400 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60 flex-shrink-0"
                onClick={() => onChange(list.filter((_, j) => j !== i))}>
                <Trash2 size={12} aria-hidden="true" />
              </button>
            </div>
          ))}
        </div>
      )}
      {remaining.length > 0 && (
        <select
          value=""
          onChange={(ev) => { if (ev.target.value) onChange([...list, ev.target.value]) }}
          aria-label="Add profile sketch"
          className="w-full h-8 px-2 text-sm bg-ink-900 border border-ink-800 rounded font-mono text-ink-100
                     focus:outline-none focus:border-kerf-300/50 focus-visible:ring-2 focus-visible:ring-kerf-300/40"
        >
          <option value="">— add a profile sketch —</option>
          {remaining.map((s) => (
            <option key={s.id} value={s.path}>{s.path}</option>
          ))}
        </select>
      )}
    </div>
  )
}

// EdgeRadiusListField — list of {edge_id, start_radius, end_radius} for the
// variable-radius fillet. v1 keeps it simple: each picked edge gets a start
// radius and an end radius (the worker fans these out into a 2-point param
// table at .at=0 and .at=1). Richer per-vertex point editing is a follow-up.
function EdgeRadiusListField({ value, onChange, pickArmed, onArmPick, selection }) {
  const rows = Array.isArray(value) ? value : []
  // Sync any newly-picked edges into the rows with default radii.
  const pickedSet = selection?.edges instanceof Set ? selection.edges : new Set()
  useEffect(() => {
    if (!pickArmed) return
    const known = new Set(rows.map((r) => r.edge_id))
    const additions = []
    for (const eid of pickedSet) {
      if (!known.has(eid)) additions.push({ edge_id: eid, radii: [{ at: 0, radius: 1 }, { at: 1, radius: 1 }] })
    }
    if (additions.length > 0) onChange([...rows, ...additions])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pickedSet.size, pickArmed])
  return (
    <div className="space-y-1">
      {rows.length === 0 ? (
        <div className="text-[11px] text-ink-500 italic">Arm pick + click edges in viewport, or use the toggle below.</div>
      ) : (
        <div className="space-y-0.5">
          {rows.map((row, i) => {
            const start = row.radii?.[0]?.radius ?? 1
            const end = row.radii?.[row.radii.length - 1]?.radius ?? start
            return (
              <div key={row.edge_id} className="flex items-center gap-1 px-1.5 py-1 bg-ink-900 border border-ink-800 rounded text-[11px] font-mono">
                <span className="text-ink-500 w-12 flex-shrink-0">edge {row.edge_id}</span>
                <input
                  type="number"
                  value={start}
                  step={0.1}
                  min={0.001}
                  aria-label={`Start radius for edge ${row.edge_id}`}
                  onChange={(ev) => {
                    const v = Number(ev.target.value)
                    const next = [...rows]
                    next[i] = { ...row, radii: [{ at: 0, radius: v }, { at: 1, radius: end }] }
                    onChange(next)
                  }}
                  className="w-14 h-6 px-1 bg-ink-800 border border-ink-700 rounded text-ink-100 focus:outline-none focus:border-kerf-300/50"
                />
                <span className="text-ink-500" aria-hidden="true">→</span>
                <input
                  type="number"
                  value={end}
                  step={0.1}
                  min={0.001}
                  aria-label={`End radius for edge ${row.edge_id}`}
                  onChange={(ev) => {
                    const v = Number(ev.target.value)
                    const next = [...rows]
                    next[i] = { ...row, radii: [{ at: 0, radius: start }, { at: 1, radius: v }] }
                    onChange(next)
                  }}
                  className="w-14 h-6 px-1 bg-ink-800 border border-ink-700 rounded text-ink-100 focus:outline-none focus:border-kerf-300/50"
                />
                <button type="button"
                  aria-label={`Remove edge ${row.edge_id}`}
                  className="text-ink-500 hover:text-red-400 ml-auto focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60"
                  onClick={() => onChange(rows.filter((_, j) => j !== i))}>
                  <Trash2 size={11} aria-hidden="true" />
                </button>
              </div>
            )
          })}
        </div>
      )}
      <button
        type="button"
        onClick={onArmPick}
        aria-label={pickArmed ? 'Stop picking edges' : 'Pick edges in viewport'}
        aria-pressed={pickArmed}
        className={`w-full px-2 h-8 rounded text-sm border transition-colors
          focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60
          ${pickArmed
            ? 'bg-kerf-300/15 border-kerf-300/40 text-kerf-200'
            : 'bg-ink-900 border-ink-800 text-ink-400 hover:text-kerf-300'}`}
      >
        {pickArmed ? 'Click edges in viewport (Esc to stop)' : 'Pick edges'}
      </button>
    </div>
  )
}

function EdgeIdsField({ value, onChange, pickArmed, onArmPick, selection, setSelection }) {
  const ids = Array.isArray(value) ? value : []
  // Sync selection set to the displayed ids when the user is actively picking.
  // (FeatureView already pushes selection into the feature; this is the reverse
  // direction — useful when the user clicks "remove" on a chip.)
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onArmPick}
          aria-label={pickArmed ? 'Stop picking edges' : 'Pick edges in viewport'}
          aria-pressed={pickArmed}
          className={`inline-flex items-center gap-1 px-2 h-7 rounded text-[11px] border
            focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60
            ${pickArmed
              ? 'bg-kerf-300/15 border-kerf-300/50 text-kerf-200'
              : 'bg-ink-800 border-ink-700 text-ink-300 hover:border-ink-500'}`}
          title={pickArmed ? 'Stop picking edges' : 'Click in the viewport to pick edges'}
        >
          <Crosshair size={11} aria-hidden="true" />
          <span>{pickArmed ? 'Picking…' : 'Pick edges'}</span>
        </button>
        <span className="text-[11px] text-ink-500">{ids.length} selected</span>
      </div>
      <div className="flex flex-wrap gap-1">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => {
              const next = ids.filter((x) => x !== id)
              onChange(next)
              // Also update the viewport selection so the highlight removes.
              const filteredEdges = new Set(
                Array.from(selection?.edgeIds || []).filter((k) => Number(k.split('|')[1]) !== id)
              )
              setSelection({ faceIds: selection?.faceIds || new Set(), edgeIds: filteredEdges })
            }}
            aria-label={`Remove edge ${id}`}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-ink-800 border border-ink-700 text-[11px] font-mono text-ink-200 hover:bg-red-900/30 hover:border-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60"
            title={`Remove edge ${id}`}
          >
            <span>e{id}</span>
            <span aria-hidden="true" className="text-ink-500">×</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function FaceIdsField({ value, onChange, pickArmed, onArmPick, selection, setSelection }) {
  const ids = Array.isArray(value) ? value : []
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <button
          type="button"
          onClick={onArmPick}
          className={`inline-flex items-center gap-1 px-2 py-1 rounded text-[11px] border
            ${pickArmed
              ? 'bg-kerf-300/15 border-kerf-300/50 text-kerf-200'
              : 'bg-ink-800 border-ink-700 text-ink-300 hover:border-ink-500'}`}
          title={pickArmed ? 'Stop picking faces' : 'Click in the viewport to pick faces'}
        >
          <Crosshair size={11} />
          <span>{pickArmed ? 'Picking…' : 'Pick faces'}</span>
        </button>
        <span className="text-[11px] text-ink-500">{ids.length} selected</span>
      </div>
      <div className="flex flex-wrap gap-1">
        {ids.map((id) => (
          <button
            key={id}
            type="button"
            onClick={() => {
              const next = ids.filter((x) => x !== id)
              onChange(next)
              const filteredFaces = new Set(
                Array.from(selection?.faceIds || []).filter((k) => Number(k.split('|')[1]) !== id)
              )
              setSelection({ edgeIds: selection?.edgeIds || new Set(), faceIds: filteredFaces })
            }}
            aria-label={`Remove face ${id}`}
            className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded bg-ink-800 border border-ink-700 text-[11px] font-mono text-ink-200 hover:bg-red-900/30 hover:border-red-700 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-red-400/60"
            title={`Remove face ${id}`}
          >
            <span>f{id}</span>
            <span aria-hidden="true" className="text-ink-500">×</span>
          </button>
        ))}
      </div>
    </div>
  )
}

function SingleFaceIdField({ value, onChange, onArmPick }) {
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        onClick={onArmPick}
        aria-label="Pick face in viewport"
        className="inline-flex items-center gap-1 px-2 h-8 rounded text-[11px] border bg-ink-800 border-ink-700 text-ink-300 hover:border-ink-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60 flex-shrink-0"
      >
        <Crosshair size={11} aria-hidden="true" />
        <span>Pick face</span>
      </button>
      <input
        type="number"
        value={value ?? ''}
        onChange={(ev) => onChange(ev.target.value === '' ? '' : Number(ev.target.value))}
        aria-label="Face ID"
        className="flex-1 h-8 px-2 bg-ink-900 border border-ink-800 rounded text-sm font-mono text-ink-100
                   focus:outline-none focus:border-kerf-300/50 focus-visible:ring-2 focus-visible:ring-kerf-300/40"
        placeholder="face id"
      />
    </div>
  )
}

function AxisField({ value, onChange, onArmPick }) {
  // value can be 'x'|'y'|'z' (string) or a numeric edge id.
  const isEdge = typeof value === 'number'
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <select
          value={isEdge ? '_edge' : (value || 'x')}
          onChange={(ev) => {
            if (ev.target.value === '_edge') return // user must arm pick
            onChange(ev.target.value)
          }}
          aria-label="Axis"
          className="flex-1 h-8 px-2 text-sm bg-ink-900 border border-ink-800 rounded text-ink-100
                     focus:outline-none focus:border-kerf-300/50 focus-visible:ring-2 focus-visible:ring-kerf-300/40"
        >
          <option value="x">X</option>
          <option value="y">Y</option>
          <option value="z">Z</option>
          <option value="_edge">{isEdge ? `Edge ${value}` : 'Pick edge…'}</option>
        </select>
        <button
          type="button"
          onClick={onArmPick}
          aria-label="Pick an edge in the viewport for axis"
          className="inline-flex items-center gap-1 px-2 h-8 rounded text-[11px] border bg-ink-800 border-ink-700 text-ink-300 hover:border-ink-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60 flex-shrink-0"
          title="Pick an edge in the viewport"
        >
          <Crosshair size={11} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}

function PlaneField({ value, onChange, onArmPick }) {
  // value can be 'xy'|'xz'|'yz' (string) or a numeric face id.
  const isFace = typeof value === 'number'
  return (
    <div className="space-y-1">
      <div className="flex items-center gap-1">
        <select
          value={isFace ? '_face' : (value || 'xy')}
          onChange={(ev) => {
            if (ev.target.value === '_face') return
            onChange(ev.target.value)
          }}
          aria-label="Plane"
          className="flex-1 h-8 px-2 text-sm bg-ink-900 border border-ink-800 rounded text-ink-100
                     focus:outline-none focus:border-kerf-300/50 focus-visible:ring-2 focus-visible:ring-kerf-300/40"
        >
          <option value="xy">XY</option>
          <option value="xz">XZ</option>
          <option value="yz">YZ</option>
          <option value="_face">{isFace ? `Face ${value}` : 'Pick face…'}</option>
        </select>
        <button
          type="button"
          onClick={onArmPick}
          aria-label="Pick a planar face in the viewport for plane"
          className="inline-flex items-center gap-1 px-2 h-8 rounded text-[11px] border bg-ink-800 border-ink-700 text-ink-300 hover:border-ink-500 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60 flex-shrink-0"
          title="Pick a planar face in the viewport"
        >
          <Crosshair size={11} aria-hidden="true" />
        </button>
      </div>
    </div>
  )
}

// Shared toolbar mode-button. Active state uses kerf-300 background +
// brighter text so it reads as "armed", not just "highlighted".
function ModeBtn({ active, onClick, icon: Icon, label, title }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      aria-label={label}
      aria-pressed={active}
      className={`inline-flex items-center gap-1.5 px-2 py-1.5 rounded-md border text-[11px] transition-colors flex-shrink-0
        focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-kerf-300/60
        ${active
          ? 'border-kerf-300/60 bg-kerf-300/20 text-kerf-100 shadow-[0_0_0_1px_rgba(255,214,51,0.2)]'
          : 'border-transparent bg-transparent text-ink-300 hover:bg-ink-800 hover:text-ink-100'}`}
    >
      <Icon size={12} aria-hidden="true" />
      <span>{label}</span>
    </button>
  )
}

// Helper: read an array-valued field on a feature node by id (for sketch-on-
// face and one-shot pick path). Tolerant of missing nodes.
function _arrayField(tree, featureId, fieldKey) {
  const n = tree.find((x) => x.id === featureId)
  return Array.isArray(n?.[fieldKey]) ? n[fieldKey] : []
}
