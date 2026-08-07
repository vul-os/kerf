// acousticsTypes.ts — shared types for src/components/acoustics/ (T-509).
//
// Local to this folder (not src/types/) — these describe the ad-hoc JSON result shapes of the
// backend's `/api/tools/call` acoustics LLM tools (ISO 9613-1/2, ISO 1996-1 NR, Sabine/Eyring
// RT60, SEA), a boundary this slice does not own. Each interface is mined field-by-field from
// the `result.<field>` reads at its call site (same convention as
// src/components/structural/structuralTypes.ts), with an `unknown` index signature for the long
// tail of fields a given tool result carries but no call site in this folder actually reads.

/** `acoustics_iso9613_outdoor` result (single-band ISO 9613-2 propagation). */
export interface Iso9613OutdoorResult {
  lp_db: number
  A_div_db: number
  A_atm_db: number
  A_gr_db: number
  A_bar_db: number
  A_total_db: number
  slant_dist_m: number
  [field: string]: unknown
}

/** One row of `acoustics_iso9613_octave_bands`'s per-band breakdown. */
export interface OctaveBandRow {
  freq_hz_input?: number | string
  freq_hz?: number | string
  lp_db: number
  A_div_db: number
  A_bar_db: number
  [field: string]: unknown
}

/** `acoustics_iso9613_octave_bands` result. */
export interface Iso9613OctaveBandsResult {
  Lp_total_db: number
  LpA_total_db: number
  per_band?: OctaveBandRow[]
  [field: string]: unknown
}

/** `acoustics_nc_rating` result. */
export interface NcRatingResult {
  nc_rating?: string | number
  exceeds_nc70?: boolean
  [field: string]: unknown
}

/** `acoustics_nr_rating` result. */
export interface NrRatingResult {
  nr_rating?: string | number
  exceeds_nr75?: boolean
  [field: string]: unknown
}

/** One resonant mode from `wave_room_modes`. */
export interface RoomMode {
  f_hz: number
  type: string
  nx: number
  ny: number
  nz: number
}

/** `wave_room_modes` result. */
export interface RoomModesResult {
  modes?: RoomMode[]
  [field: string]: unknown
}

/** One frequency-band row of `wave_sea_two_rooms_tl`'s SEA result. */
export interface SeaBandRow {
  freq_hz: number | string
  tl_db?: number
  [field: string]: unknown
}

/** `wave_sea_two_rooms_tl` result. */
export interface SeaTwoRoomsResult {
  results?: SeaBandRow[]
  [field: string]: unknown
}

/** `acoustics_apply_weighting` result. */
export interface ApplyWeightingResult {
  weighting?: string
  weighted_bands?: Record<string, number>
  [field: string]: unknown
}
