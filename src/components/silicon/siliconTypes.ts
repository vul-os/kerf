// siliconTypes.ts — shared types for src/components/silicon/ (T-510).
//
// Local to this folder (not src/types/) — these describe the SPICE analysis-panel config
// shapes and the ad-hoc JSON result shapes of the backend's `silicon_spice_*` /
// `silicon_pvt_sweep` LLM tools (a boundary this slice does not own), plus the
// `.spice.waveform` file-kind payload shared between SpiceRunPanel (producer) and
// WaveformViewer (consumer). Each interface is mined field-by-field from the
// `result.<field>` / `prop.<field>` reads at its call site (same convention as
// src/components/structural/structuralTypes.ts).

// ---------------------------------------------------------------------------
// SpiceRunPanel.tsx — analysis type / param config
// ---------------------------------------------------------------------------

export type AnalysisParamType = 'number' | 'text' | 'select'

/** One configurable parameter of an analysis type (rendered by `ParamRow`). */
export interface AnalysisParam {
  id: string
  label: string
  type: AnalysisParamType
  default: string
  min?: string
  options?: string[]
}

export type AnalysisId = 'transient' | 'ac' | 'dc_sweep' | 'pvt_corner' | 'monte_carlo'

/** One SPICE analysis mode (Transient / AC / DC Sweep / PVT Corner / Monte-Carlo). */
export interface AnalysisType {
  id: AnalysisId
  label: string
  description: string
  params: AnalysisParam[]
}

// ---------------------------------------------------------------------------
// `.spice.waveform` payload — shared between SpiceRunPanel and WaveformViewer
// ---------------------------------------------------------------------------

/** One trace in a `.spice.waveform` file: a named signal sampled over time. */
export interface WaveformSignal {
  name: string
  units: string
  t: number[]
  y: number[]
}

export interface WaveformMeta {
  title?: string
  analysis?: string
  source?: string
  ran_at?: string
  [field: string]: unknown
}

/** Full `.spice.waveform` file-kind payload. */
export interface WaveformData {
  signals: WaveformSignal[]
  meta?: WaveformMeta
}

// ---------------------------------------------------------------------------
// Backend tool results — `silicon_spice_transient/ac/dc/monte_carlo`, `silicon_pvt_sweep`
// ---------------------------------------------------------------------------

/** One (corner × metric) row of a `silicon_pvt_sweep` result. */
export interface PvtCornerRow {
  metric: string
  temp_c: number | string
  mean: number
  unit?: string
  [field: string]: unknown
}

/** `silicon_pvt_sweep` result, wrapped one level under `resp.result`. */
export interface PvtSweepResult {
  results?: PvtCornerRow[]
  error?: string
  warnings?: string[]
  [field: string]: unknown
}

/** Standard SPICE waveform tool result — `{ waveforms: { time/t: [], "v(out)": [], ... } }`. */
export interface SpiceWaveformResult {
  waveforms?: Record<string, number[]>
  warnings?: string[]
  error?: string
  [field: string]: unknown
}

/** Envelope `api.callTool()` may return: either the raw tool result, or `{ result, error }`. */
export interface SpiceToolResponse {
  result?: PvtSweepResult | SpiceWaveformResult
  error?: string
  waveforms?: Record<string, number[]>
  warnings?: string[]
  [field: string]: unknown
}
