// structuralTypes.ts — shared types for src/components/structural/ (T-509).
//
// Local to this folder (not src/types/) — these describe the ad-hoc JSON result shapes of the
// backend's `/api/tools/call` structural/seismic/rebar LLM tools (AISC 360-22, ACI 318-19,
// BS 8666:2020, ASCE 7-22), a boundary this slice does not own. Each interface is mined
// field-by-field from the `result.<field>` reads at its call site (same convention as
// src/components/fea/femTypes.ts), with an `unknown` index signature for the long tail of
// fields a given tool result carries but no call site in this folder actually reads.

// ---------------------------------------------------------------------------
// StructuralMemberPanel.tsx — AISC 360-22 / ACI 318-19 tool results
// ---------------------------------------------------------------------------

/** `aisc_member_check` result (Ch E + F + H combined interaction check). */
export interface AiscMemberCheckResult {
  interaction_ok: boolean
  ratio_H1: number
  phi_Pn_kips: number
  KL_r: number
  Fcr_ksi: number
  phi_Mnx_kip_ft: number
  phi_Mny_kip_ft: number
  ltb_zone: string
  flange_slenderness: string | number
  governing: string
  [field: string]: unknown
}

/** `aisc_compression` result (Ch E axial capacity only). */
export interface AiscCompressionResult {
  ok: boolean
  phi_Pn_kips: number
  Fcr_ksi?: number
  [field: string]: unknown
}

/** `aisc_flexure` result (Ch F flexural capacity only). */
export interface AiscFlexureResult {
  ok: boolean
  phi_Mn_kip_ft: number
  Mp_kip_in?: number
  Lp_ft?: number
  Lr_ft?: number
  ltb_zone: string
  flange_slenderness: string | number
  web_slenderness: string | number
  Mn_over_Omega_kip_ft?: number
  [field: string]: unknown
}

/** `structural_rc_beam` result (ACI 318-19 singly-reinforced beam design). */
export interface AciRcBeamResult {
  ok: boolean
  As_required_in2: number
  d: number
  Rn_psi: number
  rho: number
  rho_min: number
  rho_max: number
  [field: string]: unknown
}

/** `structural_rebar` result (ACI 318-19 §25 development/lap-splice lengths). */
export interface AciRebarResult {
  bar_mark: string | number
  splice_class: string
  diameter_in: number
  area_in2: number
  ld_in: number
  lap_length_in: number
  [field: string]: unknown
}

// ---------------------------------------------------------------------------
// RebarDetailPanel.tsx — BS 8666:2020 3D rebar detailing / schedule / shop drawing
// ---------------------------------------------------------------------------

/** One placed bar (longitudinal bar or stirrup/tie) from `rebar_detail_member`. */
export interface RebarBar {
  mark: string
  role: string
  shape_code: string
  diameter_mm: number
  count: number
  cut_length_mm?: number
  mass_kg?: number
  /** Flat list of [x, y, (z)] polyline points describing the bar's 3D path. */
  centreline?: number[][]
}

export interface RebarSection {
  width_mm: number
  depth_mm: number
  cover_mm: number
  length_mm: number
}

/** `rebar_detail_member` result. */
export interface RebarDetailResult {
  ok: boolean
  error?: string
  section: RebarSection
  longitudinal_bars: RebarBar[]
  stirrups: RebarBar[]
  all_bars: RebarBar[]
  summary: {
    total_bar_count: number
    total_mass_kg?: number
  }
}

/** One row of `rebar_bending_schedule`'s bar-bending schedule table. */
export interface RebarScheduleRow {
  member_ref: string
  bar_mark: string
  bar_type: string
  diameter_mm: number
  shape_code: string
  cut_length_mm?: number
  number_of_bars?: number
  total_length_m?: number
  mass_kg?: number
}

/** `rebar_bending_schedule` result. */
export interface RebarScheduleResult {
  ok: boolean
  error?: string
  rows: RebarScheduleRow[]
  summary?: {
    total_mass_kg?: number
    total_bars?: number
    row_count?: number
  }
}

/**
 * One shop-drawing sheet entity, discriminated by `type`. Field lists come from
 * `RebarDetailPanel.jsx`'s `DrawingSheetPreview` renderer (the only consumer) — its bbox
 * probe (`'x' in e`, `'x1' in e`, `'cx' in e`, ...) confirms exactly these shapes appear.
 */
export type DrawingEntity =
  | { type: 'line'; x1: number; y1: number; x2: number; y2: number; layer?: string; style?: string }
  | { type: 'rect'; x: number; y: number; w: number; h: number; layer?: string }
  | { type: 'circle'; cx: number; cy: number; r: number; layer?: string }
  | { type: 'text'; x: number; y: number; text: string; size?: number; anchor?: 'start' | 'middle' | 'end'; layer?: string }
  | { type: 'leader'; x_tip: number; y_tip: number; x_text: number; y_text: number; text: string; layer?: string }
  | { type: 'dimension'; x1: number; y1: number; x2: number; y2: number; mid_x: number; mid_y: number; value: string | number; layer?: string }

export interface DrawingSheet {
  sheet_number: number | string
  title: string
  entity_count?: number
  entities: DrawingEntity[]
}

/** `shop_drawing_generate` result. */
export interface ShopDrawingResult {
  ok: boolean
  error?: string
  sheets: DrawingSheet[]
  summary: {
    sheets: number
    total_bars: number
    total_mass_kg?: number
  }
  title_block?: {
    drawing_number?: string
    scale?: string
    project_name?: string
  }
}

// ---------------------------------------------------------------------------
// SeismicRSAPanel.tsx — ASCE 7-22 response-spectrum analysis tool results
// ---------------------------------------------------------------------------

/** `seismic_build_asce7_spectrum` result. */
export interface SeismicSpectrumResult {
  ok: boolean
  reason?: string
  T0: number
  Ts: number
  TL: number
  SDS: number
  /** [period_s, Sa_g] pairs. */
  spectrum: Array<[number, number]>
  warnings?: string[]
  [field: string]: unknown
}

/** `seismic_rsa_sdof` result, plus the two spectrum fields SDOF tab merges in locally. */
export interface SeismicSdofResult {
  T_n: number
  omega_n: number
  Sa_g: number
  Sa_ms2: number
  Sd_m: number
  peak_disp_m: number
  peak_force_N: number
  warnings?: string[]
  T0?: number
  Ts?: number
  [field: string]: unknown
}

/** `seismic_rsa_mdof` result (multi-mode RSA, SRSS/CQC). */
export interface SeismicMdofResult {
  base_shear_N: number
  base_moment_Nm?: number
  method: string
  n_modes: number
  n_dofs: number
  mode_Sa_g: number[]
  mode_shear_N: number[]
  combined_disp_m: number[]
  warnings?: string[]
  [field: string]: unknown
}

/** `seismic_newmark_sdof` result (Newmark-β time-history integration). */
export interface SeismicNewmarkResult {
  T_n: number
  omega_n: number
  peak_u_m: number
  peak_v_ms: number
  peak_a_ms2: number
  u?: number[]
  warnings?: string[]
  [field: string]: unknown
}
