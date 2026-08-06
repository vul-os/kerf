// brepTypes.ts — shared types for src/components/brep/ (T-509).
//
// Local to this folder (not src/types/) — GeometryInspector.tsx and AssemblyClashPanel.tsx each
// build a generic "tool card" UI over ~30 distinct `brep_*` / `assembly_*` backend LLM tools
// (routes_tools.py, POST /api/tools/call). Each tool's request args and result JSON shape is
// genuinely tool-specific and this slice does not own that backend contract, so the field-level
// shape is intentionally left as `unknown`/`Record<string, unknown>` rather than modeled
// per-tool — the UI itself only ever reads a handful of optional, defensively-guarded fields
// (see InterferenceRow below for the one shape worth naming).

import type { LucideIcon } from 'lucide-react'

/** One input field in a ToolCard's generated form (GeometryInspector.tsx). */
export interface CardField {
  key: string
  label: string
  type?: 'text' | 'number' | 'select' | 'textarea'
  placeholder?: string
  default?: string
  options?: Array<{ value: string; label: string }>
}

/** One tool card definition — a `brep_*` tool wired into a form + run button. */
export interface ToolCardDef {
  name: string
  icon?: LucideIcon
  color?: string
  desc?: string
  fields: CardField[]
  /** Builds the tool call's `args` from the form's raw string values. */
  buildArgs?: (values: Record<string, string>) => Record<string, unknown>
}

/**
 * One row of AssemblyClashPanel's interference table. Field names vary by which tool produced
 * the row (`brep_assembly_interference` vs. a raw array vs. a synthesized single-pair result),
 * hence the alias fields — every read at the call site already goes through a `??` chain across
 * these exact aliases.
 */
export interface InterferenceRow {
  body_a?: string
  component_a?: string
  body_b?: string
  component_b?: string
  overlap_volume?: number | string
  penetration_volume?: number | string
  volume?: number | string
  face_count?: number
  faces?: number
}
